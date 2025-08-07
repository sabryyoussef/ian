# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from collections import defaultdict

_logger = logging.getLogger(__name__)


# OLD FUNCTION - REPLACED BY DOCUMENT SERVICE
# def copy_documents_from_product_to_project(env, project, product_templates):
#     """This function has been replaced by the Document Service pattern"""
#     pass


def copy_documents_from_project_to_task(env, task, project):
    """Copy document types from project to task"""
    # Copy required documents if they exist
    if hasattr(project, 'document_required_type_ids') and project.document_required_type_ids:
        for req_doc in project.document_required_type_ids:
            env['project.document.required.line'].create({
                'task_id': task.id,
                'document_type_id': req_doc.document_type_id.id,
                'is_required': req_doc.is_required,
            })
    # Copy deliverable documents if they exist
    if hasattr(project, 'document_type_ids') and project.document_type_ids:
        for del_doc in project.document_type_ids:
            env['project.document.type.line'].create({
                'task_id': task.id,
                'document_type_id': del_doc.document_type_id.id,
                'is_required': del_doc.is_required,
            })

def copy_checkpoints_from_template_to_task(env, task, template):
    """Copy checkpoint configurations from product task template to task"""
    if hasattr(template, 'checkpoint_ids') and template.checkpoint_ids:
        for checkpoint_config in template.checkpoint_ids:
            env['task.checkpoint'].create({
                'task_id': task.id,
                'checkpoint_ids': [(6, 0, checkpoint_config.checkpoint_ids.ids)],
                'stage_id': checkpoint_config.stage_id.id if checkpoint_config.stage_id else False,
                'milestone_id': checkpoint_config.milestone_id.id if checkpoint_config.milestone_id else False,
                'sequence': checkpoint_config.sequence,
            })


class ProjectDocumentCategory(models.Model):
    _name = 'project.document.category'
    _description = 'Project Document Category'
    _rec_name = 'name'

    name = fields.Char('Category Name', required=True)
    description = fields.Text('Description')
    document_type_ids = fields.One2many('project.document.type', 'category_id', string='Document Types')


class ProjectDocumentType(models.Model):
    _name = 'project.document.type'
    _description = 'Project Document Type'

    name = fields.Char('Type Name', required=True)
    category_id = fields.Many2one('project.document.category', string='Category')
    description = fields.Text('Description')
    is_required = fields.Boolean('Required', default=False)
    expiry_required = fields.Boolean('Expiry Required', default=False)
    reminder_days = fields.Integer('Reminder Days', default=30, help='Days before expiry to send reminder')
    document_ids = fields.One2many('project.document.type.line', 'document_type_id', string='Document Lines')


class ProjectDocumentTypeLine(models.Model):
    _name = 'project.document.type.line'
    _description = 'Project Deliverable Document Type Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', ondelete='cascade')
    document_type_id = fields.Many2one('project.document.type', string='Document Type', required=True)
    document_id = fields.Many2one('documents.document', string='Document', required=False)
    is_required = fields.Boolean(string='Required', default=False)
    expiry_date = fields.Date('Expiry Date')
    reminder_days = fields.Integer('Reminder Days', default=30)
    is_expired = fields.Boolean('Is Expired', default=False)
    is_verify = fields.Boolean('Is Verified', default=False)
    number = fields.Char(
        string="Number",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    issue_date = fields.Date(
        default=fields.Date.today,
        help="Date when the document was issued",
    )
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    expiration_reminder = fields.Boolean(default=False)
    expiration_reminder_sent = fields.Boolean(default=False)
    document_create_date = fields.Datetime(
        readonly=True,
        string="Document Create Date",
        default=fields.datetime.now(),
    )

    @api.depends('expiry_date')
    def _compute_expired(self):
        """Compute document expiry status with smooth error handling"""
        try:
            today = fields.Date.today()
            _logger.info(f"Computing expiry status for {len(self)} documents")
            for record in self:
                try:
                    if record.expiry_date:
                        is_expired = record.expiry_date < today
                        record.is_expired = is_expired
                        if is_expired:
                            _logger.warning(f"Document {record.id} ({getattr(record, 'document_type_id', False) and record.document_type_id.name or 'Unknown'}) is EXPIRED (expiry: {record.expiry_date})")
                        else:
                            _logger.info(f"Document {record.id} ({getattr(record, 'document_type_id', False) and record.document_type_id.name or 'Unknown'}) is VALID (expiry: {record.expiry_date})")
                    else:
                        record.is_expired = False
                        _logger.debug(f"Document {record.id} has no expiry date set")
                except Exception as e:
                    _logger.error(f"Error computing expiry for document {record.id}: {str(e)}")
                    record.is_expired = False
        except Exception as e:
            _logger.error(f"Error in document expiry computation: {str(e)}")
            for record in self:
                record.is_expired = False

    def action_numbers(self):
        docs = self.env['project.document.type.line'].sudo().search([])
        for doc in docs:
            doc.number = self.env['ir.sequence'].next_by_code('project.document.type.line') or _("New")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'number' not in vals:
                vals['number'] = self.env['ir.sequence'].next_by_code('project.document.type.line') or _("New")
        records = super(ProjectDocumentTypeLine, self).create(vals_list)
        
        # Check for duplicates after creation
        for record in records:
            record._check_duplicate_after_create()
        
        return records

    def _check_duplicate_after_create(self):
        """Check for duplicates after document creation"""
        _logger.info(f"Checking for duplicates after create for required document {self.id}")
        
        try:
            # Build domain to find potential duplicates
            domain = [
                ('document_type_id', '=', self.document_type_id.id),
                ('id', '!=', self.id)
            ]
            
            # Add context-specific conditions
            if self.project_id:
                domain.append(('project_id', '=', self.project_id.id))
                context_info = f" in project {self.project_id.name}"
            elif self.task_id:
                domain.append(('task_id', '=', self.task_id.id))
                context_info = f" in task {self.task_id.name}"
            elif self.product_tmpl_id:
                domain.append(('product_tmpl_id', '=', self.product_tmpl_id.id))
                context_info = f" in product {self.product_tmpl_id.name}"
            else:
                context_info = ""
            
            duplicate_documents = self.search(domain)
            _logger.info(f"Found {len(duplicate_documents)} potential duplicates for required document {self.id}")
            
            if duplicate_documents:
                _logger.info(f"Duplicate required documents found: {duplicate_documents.ids}")
                
                for duplicate in duplicate_documents:
                    # Check if attachments are the same
                    if self.attachment_ids and duplicate.attachment_ids:
                        self_attachment_ids = set(self.attachment_ids.mapped('id'))
                        dup_attachment_ids = set(duplicate.attachment_ids.mapped('id'))
                        
                        if self_attachment_ids == dup_attachment_ids and self_attachment_ids:
                            _logger.info(f"Duplicate required document detected with same attachments: {self.id} vs {duplicate.id}")
                            
                            # Post warning to project chatter
                            if self.project_id:
                                self.project_id.message_post(
                                    body=_("⚠️ Duplicate required document detected: %s with same attachments as existing document%s") % (
                                        self.document_type_id.name, context_info
                                    )
                                )
                            
                            # Prevent saving by raising ValidationError
                            raise ValidationError(_("⚠️ Duplicate required document detected: %s with same attachments as existing document%s") % (
                                self.document_type_id.name, context_info
                            ))
                    else:
                        # If no attachments, check for same document type in same context
                        _logger.info(f"Duplicate required document detected (same document type): {self.id} vs {duplicate.id}")
                        
                        # Post warning to project chatter
                        if self.project_id:
                            self.project_id.message_post(
                                body=_("⚠️ Duplicate required document detected: %s (same document type)%s") % (
                                    self.document_type_id.name, context_info
                                )
                            )
                        
                        # Prevent saving by raising ValidationError
                        raise ValidationError(_("⚠️ Duplicate required document detected: %s (same document type)%s") % (
                            self.document_type_id.name, context_info
                        ))
                        
        except ValidationError:
            # Re-raise ValidationError to prevent saving
            raise
        except Exception as e:
            _logger.error(f"Error checking duplicate after create for required document {self.id}: {str(e)}")
            import traceback
            _logger.error(f"Full traceback: {traceback.format_exc()}")

    @api.constrains('project_id', 'task_id', 'product_tmpl_id', 'document_type_id')
    def check_duplicate_document(self):
        """Enhanced duplicate detection with multi-product support"""
        for record in self:
            if not record.document_type_id:
                continue
                
            # Build enhanced domain based on context
            domain = [
                ('document_type_id', '=', record.document_type_id.id),
                ('id', '!=', record.id)
            ]
            
            # Enhanced context-specific filtering
            if record.product_tmpl_id:
                domain.append(('product_tmpl_id', '=', record.product_tmpl_id.id))
                context_name = f"{record.product_tmpl_id.name} - {record.document_type_id.name}"
            elif record.project_id:
                domain.append(('project_id', '=', record.project_id.id))
                context_name = f"{record.project_id.name} - {record.document_type_id.name}"
            elif record.task_id:
                domain.append(('task_id', '=', record.task_id.id))
                context_name = f"{record.task_id.name} - {record.document_type_id.name}"
            else:
                continue  # Skip if no context
            
            # Enhanced duplicate detection with scoring
            duplicates = self.search(domain)
            if duplicates:
                # Enhanced error message with more details
                duplicate_info = []
                for dup in duplicates:
                    dup_context = ""
                    if dup.product_tmpl_id:
                        dup_context = f"Product: {dup.product_tmpl_id.name}"
                    elif dup.project_id:
                        dup_context = f"Project: {dup.project_id.name}"
                    elif dup.task_id:
                        dup_context = f"Task: {dup.task_id.name}"
                    
                    duplicate_info.append(f"• {dup.document_type_id.name} in {dup_context}")
                
                raise ValidationError(_(
                    "⚠️ Duplicate document detected: '%s' already exists in:\n%s\n\n"
                    "Context: %s"
                ) % (record.document_type_id.name, '\n'.join(duplicate_info), context_name))

    def write(self, vals):
        _logger.info(f"📝 Write called for ProjectDocumentTypeLine with vals: {vals}")
        res = super(ProjectDocumentTypeLine, self).write(vals)
        if vals.get('expiry_date'):
            self.write({'expiration_reminder_sent': False})
        if vals.get('attachment_ids'):
            _logger.info(f"📎 Attachment_ids detected: {vals.get('attachment_ids')}")
            self.write({'document_create_date': fields.Datetime.today()})
            # Convert new attachments to documents
            self._convert_attachments_to_documents()
        return res
    
    def _convert_attachments_to_documents(self):
        """Convert attachments to documents and place them in project folder"""
        for record in self:
            if not record.project_id:
                continue
                
            _logger.info(f"🔄 Converting attachments to documents for {record.document_type_id.name}")
            
            # Ensure project has a folder
            record.project_id._ensure_project_folder()
            
            for attachment in record.attachment_ids:
                # Check if this attachment is already converted to a document
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                
                if existing_doc:
                    _logger.info(f"📄 Attachment {attachment.name} already converted to document {existing_doc.id}")
                    continue
                
                try:
                    # Create document from attachment
                    document_vals = {
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': 'project.project',
                        'res_id': record.project_id.id,
                        'type': 'file',
                    }
                    
                    # Add folder if project has one
                    if record.project_id.documents_folder_id:
                        document_vals['folder_id'] = record.project_id.documents_folder_id.id
                    
                    document = self.env['documents.document'].create(document_vals)
                    _logger.info(f"✅ Converted attachment '{attachment.name}' to document {document.id}")
                    
                    # Update the document line with the created document
                    if not record.document_id:
                        record.document_id = document.id
                        _logger.info(f"🔗 Linked document {document.id} to document line {record.id}")
                    
                except Exception as e:
                    _logger.error(f"❌ Failed to convert attachment '{attachment.name}' to document: {e}")

    def action_upload_document(self):
        """Action to upload document for this line"""
        self.ensure_one()
        _logger.info(f"🔥🔥🔥 ACTION_UPLOAD_DOCUMENT BUTTON CLICKED for line {self.id}")
        _logger.info(f"🚀🚀🚀 Upload document action triggered for document line {self.id} (type: {self.document_type_id.name})")
        
        context = {
            'default_name': self.document_type_id.name,
            'default_document_type': 'deliverable' if self.project_id else 'required',
            'default_project_id': self.project_id.id if self.project_id else False,
            'default_task_id': self.task_id.id if self.task_id else False,
            'default_document_line_id': self.id,
            'default_user_id': self.env.user.id,
        }
        
        _logger.info(f"📋 Context for wizard: {context}")
        _logger.info(f"🎯 RETURNING WIZARD ACTION: document.upload.wizard")
        
        return {
            'name': _('Upload Document'),
            'type': 'ir.actions.act_window',
            'res_model': 'document.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

    def _trigger_duplicate_popup(self, message):
        """Trigger a popup notification for duplicate detection"""
        try:
            # Set context flag for notification
            self.env.context = dict(self.env.context, 
                duplicate_warning=True, 
                duplicate_message=message,
                duplicate_title=_('Duplicate Document Detected')
            )
            
            # Log the notification
            _logger.info(f"Duplicate popup triggered: {message}")
            
            return True
            
        except Exception as e:
            _logger.error(f"Error triggering duplicate popup: {str(e)}")
            return False
    
    def action_convert_attachments_to_documents(self):
        """Manual action to convert attachments to documents"""
        self.ensure_one()
        _logger.info(f"🔧 Manual conversion triggered for document line {self.id}")
        self._convert_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Attachments converted to documents successfully'),
                'type': 'success',
            }
        }
    
    def action_save_and_convert_attachments(self):
        """Save the record and convert attachments"""
        self.ensure_one()
        _logger.info(f"💾 Save and convert triggered for document line {self.id}")
        
        # Save the record first
        self.write({})
        
        # Then convert attachments
        if self.attachment_ids:
            _logger.info(f"📎 Found {len(self.attachment_ids)} attachments to convert")
            self._convert_attachments_to_documents()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _(f'Converted {len(self.attachment_ids)} attachments to documents'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Info'),
                    'message': _('No attachments found to convert'),
                    'type': 'info',
                }
            }


class ProjectDocumentRequiredLine(models.Model):
    _name = 'project.document.required.line'
    _description = 'Project Required Document Type Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', ondelete='cascade')
    document_type_id = fields.Many2one('project.document.type', string='Document Type', required=True)
    document_id = fields.Many2one('documents.document', string='Document', required=False)
    is_required = fields.Boolean(string='Required', default=False)
    expiry_date = fields.Date('Expiry Date')
    reminder_days = fields.Integer('Reminder Days', default=30)
    is_expired = fields.Boolean('Is Expired', default=False)
    is_verify = fields.Boolean('Is Verified', default=False)
    number = fields.Char(
        string="Number",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    issue_date = fields.Date(
        default=fields.Date.today,
        help="Date when the document was issued",
    )
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    expiration_reminder = fields.Boolean(default=False)
    expiration_reminder_sent = fields.Boolean(default=False)
    document_create_date = fields.Datetime(
        readonly=True,
        string="Document Create Date",
        default=fields.datetime.now(),
    )

    @api.depends('expiry_date')
    def _compute_expired(self):
        """Compute document expiry status with smooth error handling"""
        try:
            today = fields.Date.today()
            _logger.info(f"Computing expiry status for {len(self)} required documents")
            for record in self:
                try:
                    if record.expiry_date:
                        is_expired = record.expiry_date < today
                        record.is_expired = is_expired
                        if is_expired:
                            _logger.warning(f"Required Document {record.id} ({getattr(record, 'document_type_id', False) and record.document_type_id.name or 'Unknown'}) is EXPIRED (expiry: {record.expiry_date})")
                        else:
                            _logger.info(f"Required Document {record.id} ({getattr(record, 'document_type_id', False) and record.document_type_id.name or 'Unknown'}) is VALID (expiry: {record.expiry_date})")
                    else:
                        record.is_expired = False
                        _logger.debug(f"Required Document {record.id} has no expiry date set")
                except Exception as e:
                    _logger.error(f"Error computing expiry for required document {record.id}: {str(e)}")
                    record.is_expired = False
        except Exception as e:
            _logger.error(f"Error in required document expiry computation: {str(e)}")
            for record in self:
                record.is_expired = False

    def action_numbers(self):
        docs = self.env['project.document.required.line'].sudo().search([])
        for doc in docs:
            doc.number = self.env['ir.sequence'].next_by_code('project.document.required.line') or _("New")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'number' not in vals:
                vals['number'] = self.env['ir.sequence'].next_by_code('project.document.required.line') or _("New")
        records = super(ProjectDocumentRequiredLine, self).create(vals_list)
        
        # Check for duplicates after creation
        for record in records:
            record._check_duplicate_after_create()
        
        return records

    def _check_duplicate_after_create(self):
        """Check for duplicates after document creation"""
        _logger.info(f"🔍 DEBUG: _check_duplicate_after_create called for required document {self.id}")
        _logger.info(f"🔍 DEBUG: Document type: {self.document_type_id.name if self.document_type_id else 'None'}")
        _logger.info(f"🔍 DEBUG: Product template: {self.product_tmpl_id.name if self.product_tmpl_id else 'None'}")
        _logger.info(f"🔍 DEBUG: Project: {self.project_id.name if self.project_id else 'None'}")
        _logger.info(f"🔍 DEBUG: Attachments: {len(self.attachment_ids)}")
        
        try:
            # Build domain for duplicate check - check multiple criteria
            domain = [
                ('document_type_id', '=', self.document_type_id.id),
                ('id', '!=', self.id),
            ]
            
            # Add project/task/product filters
            if self.project_id:
                domain.append(('project_id', '=', self.project_id.id))
            if self.task_id:
                domain.append(('task_id', '=', self.task_id.id))
            if self.product_tmpl_id:
                domain.append(('product_tmpl_id', '=', self.product_tmpl_id.id))
            
            _logger.info(f"🔍 DEBUG: Search domain: {domain}")
            
            # Search for duplicates with same document type and project/task/product
            duplicate_documents = self.search(domain)
            _logger.info(f"🔍 DEBUG: Found {len(duplicate_documents)} potential duplicates")
            
            if duplicate_documents:
                _logger.info(f"🔍 DEBUG: Checking {len(duplicate_documents)} duplicates for attachments")
                # Check if any duplicates have the same attachments
                for duplicate in duplicate_documents:
                    _logger.info(f"🔍 DEBUG: Checking duplicate {duplicate.id} with {len(duplicate.attachment_ids)} attachments")
                    if self.attachment_ids and duplicate.attachment_ids:
                        # Check if attachments are the same
                        self_attachment_ids = set(self.attachment_ids.ids)
                        dup_attachment_ids = set(duplicate.attachment_ids.ids)
                        
                        _logger.info(f"🔍 DEBUG: Self attachments: {self_attachment_ids}")
                        _logger.info(f"🔍 DEBUG: Duplicate attachments: {dup_attachment_ids}")
                        
                        if self_attachment_ids == dup_attachment_ids and self_attachment_ids:
                            context_info = ""
                            if self.product_tmpl_id:
                                context_info = f" in product {self.product_tmpl_id.name}"
                            elif self.project_id:
                                context_info = f" in project {self.project_id.name}"
                            
                            _logger.warning(f"Duplicate required document detected for {self.document_type_id.name} with same attachments{context_info}")
                            # Post warning message to project chatter
                            if self.project_id:
                                self.project_id.message_post(
                                    body=_("🚨 POPUP_WARNING: Duplicate required document detected: %s with same attachments as existing document%s") % (
                                        self.document_type_id.name, context_info
                                    )
                                )
                            # Trigger popup notification
                            self._trigger_duplicate_popup(_('🚨 POPUP_WARNING: Duplicate required document detected: %s with same attachments as existing document%s') % (
                                self.document_type_id.name, context_info
                            ))
                            break
                    else:
                        # If no attachments, check for same document type in same context
                        context_info = ""
                        if self.product_tmpl_id:
                            context_info = f" in product {self.product_tmpl_id.name}"
                        elif self.project_id:
                            context_info = f" in project {self.project_id.name}"
                        
                        _logger.warning(f"Duplicate required document detected for {self.document_type_id.name} (same type){context_info}")
                        # Post warning message to project chatter
                        if self.project_id:
                            self.project_id.message_post(
                                body=_("🚨 POPUP_WARNING: Duplicate required document detected: %s (same document type)%s") % (
                                    self.document_type_id.name, context_info
                                )
                            )
                        # Trigger popup notification
                        self._trigger_duplicate_popup(_('🚨 POPUP_WARNING: Duplicate required document detected: %s (same document type)%s') % (
                            self.document_type_id.name, context_info
                        ))
                        break
            else:
                _logger.info(f"🔍 DEBUG: No duplicates found")
                    
        except Exception as e:
            _logger.error(f"Error checking duplicate after create for required document {self.id}: {str(e)}")
            import traceback
            _logger.error(f"Full traceback: {traceback.format_exc()}")

    @api.constrains('project_id', 'task_id', 'product_tmpl_id', 'document_type_id')
    def check_duplicate_document(self):
        """Enhanced duplicate detection for required documents with multi-product support"""
        for record in self:
            if not record.document_type_id:
                continue
                
            # Build enhanced domain based on context
            domain = [
                ('document_type_id', '=', record.document_type_id.id),
                ('id', '!=', record.id)
            ]
            
            # Enhanced context-specific filtering
            if record.product_tmpl_id:
                domain.append(('product_tmpl_id', '=', record.product_tmpl_id.id))
                context_name = f"{record.product_tmpl_id.name} - {record.document_type_id.name}"
            elif record.project_id:
                domain.append(('project_id', '=', record.project_id.id))
                context_name = f"{record.project_id.name} - {record.document_type_id.name}"
            elif record.task_id:
                domain.append(('task_id', '=', record.task_id.id))
                context_name = f"{record.task_id.name} - {record.document_type_id.name}"
            else:
                continue  # Skip if no context
            
            # Enhanced duplicate detection with scoring
            duplicates = self.search(domain)
            if duplicates:
                # Enhanced error message with more details
                duplicate_info = []
                for dup in duplicates:
                    dup_context = ""
                    if dup.product_tmpl_id:
                        dup_context = f"Product: {dup.product_tmpl_id.name}"
                    elif dup.project_id:
                        dup_context = f"Project: {dup.project_id.name}"
                    elif dup.task_id:
                        dup_context = f"Task: {dup.task_id.name}"
                    
                    duplicate_info.append(f"• {dup.document_type_id.name} in {dup_context}")
                
                raise ValidationError(_(
                    "⚠️ Duplicate required document detected: '%s' already exists in:\n%s\n\n"
                    "Context: %s"
                ) % (record.document_type_id.name, '\n'.join(duplicate_info), context_name))

    def write(self, vals):
        _logger.info(f"📝 Write called for ProjectDocumentRequiredLine with vals: {vals}")
        res = super(ProjectDocumentRequiredLine, self).write(vals)
        if vals.get('expiry_date'):
            self.write({'expiration_reminder_sent': False})
        if vals.get('attachment_ids'):
            _logger.info(f"📎 Attachment_ids detected: {vals.get('attachment_ids')}")
            self.write({'document_create_date': fields.Datetime.today()})
            # Convert new attachments to documents
            self._convert_attachments_to_documents()
        return res
    
    def _convert_attachments_to_documents(self):
        """Convert attachments to documents and place them in project folder"""
        for record in self:
            if not record.project_id:
                continue
                
            _logger.info(f"🔄 Converting attachments to documents for {record.document_type_id.name}")
            
            # Ensure project has a folder
            record.project_id._ensure_project_folder()
            
            for attachment in record.attachment_ids:
                # Check if this attachment is already converted to a document
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                
                if existing_doc:
                    _logger.info(f"📄 Attachment {attachment.name} already converted to document {existing_doc.id}")
                    continue
                
                try:
                    # Create document from attachment
                    document_vals = {
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': 'project.project',
                        'res_id': record.project_id.id,
                        'type': 'file',
                    }
                    
                    # Add folder if project has one
                    if record.project_id.documents_folder_id:
                        document_vals['folder_id'] = record.project_id.documents_folder_id.id
                    
                    document = self.env['documents.document'].create(document_vals)
                    _logger.info(f"✅ Converted attachment '{attachment.name}' to document {document.id}")
                    
                    # Update the document line with the created document
                    if not record.document_id:
                        record.document_id = document.id
                        _logger.info(f"🔗 Linked document {document.id} to document line {record.id}")
                    
                except Exception as e:
                    _logger.error(f"❌ Failed to convert attachment '{attachment.name}' to document: {e}")

    def action_upload_document(self):
        """Action to upload document for this line"""
        self.ensure_one()
        _logger.info(f"🚀 Upload document action triggered for required document line {self.id} (type: {self.document_type_id.name})")
        
        context = {
            'default_name': self.document_type_id.name,
            'default_document_type': 'required',
            'default_project_id': self.project_id.id if self.project_id else False,
            'default_task_id': self.task_id.id if self.task_id else False,
            'default_document_line_id': self.id,
        }
        
        _logger.info(f"📋 Context for wizard: {context}")
        
        return {
            'name': _('Upload Document'),
            'type': 'ir.actions.act_window',
            'res_model': 'document.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }
    
    def action_convert_attachments_to_documents(self):
        """Manual action to convert attachments to documents"""
        self.ensure_one()
        _logger.info(f"🔧 Manual conversion triggered for required document line {self.id}")
        self._convert_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Attachments converted to documents successfully'),
                'type': 'success',
            }
        }
    
    def action_save_and_convert_attachments(self):
        """Save the record and convert attachments"""
        self.ensure_one()
        _logger.info(f"💾 Save and convert triggered for required document line {self.id}")
        
        # Save the record first
        self.write({})
        
        # Then convert attachments
        if self.attachment_ids:
            _logger.info(f"📎 Found {len(self.attachment_ids)} attachments to convert")
            self._convert_attachments_to_documents()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _(f'Converted {len(self.attachment_ids)} attachments to documents'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Info'),
                    'message': _('No attachments found to convert'),
                    'type': 'info',
                }
            }


# Temporarily disable NEW PROJECT-LEVEL DOCUMENT MODELS to isolate transaction issues
# --- NEW PROJECT-LEVEL DOCUMENT MODELS ---

if False:  # Disable these models temporarily
    class ProjectLevelRequiredDocument(models.Model):
        _name = 'project.level.required.document'
        _description = 'Project Level Required Document'
        _order = 'sequence, id'

        project_id = fields.Many2one('project.project', string='Project', required=True, ondelete='cascade')
        document_type_id = fields.Many2one('project.document.type', string='Document Type', required=True)
        document_id = fields.Many2one('documents.document', string='Document', required=True)
        sequence = fields.Integer(string='Sequence', default=10)
        is_required = fields.Boolean(string='Required', default=True)
        is_verified = fields.Boolean(string='Verified', default=False)
        verification_date = fields.Date(string='Verification Date')
        verified_by = fields.Many2one('res.users', string='Verified By')
        expiry_date = fields.Date('Expiry Date')
        reminder_days = fields.Integer('Reminder Days', default=30)
        is_expired = fields.Boolean('Is Expired', default=False)
        number = fields.Char(
            string="Number",
            required=True,
            copy=False,
            readonly=True,
            index=True,
            default=lambda self: _("New"),
        )
        issue_date = fields.Date(
            default=fields.Date.today,
            help="Date when the document was issued",
        )
        attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
        expiration_reminder = fields.Boolean(default=False)
        expiration_reminder_sent = fields.Boolean(default=False)
        document_create_date = fields.Datetime(
            readonly=True,
            string="Document Create Date",
            default=fields.datetime.now(),
        )

        # @api.depends('expiry_date')
        # def _compute_expired(self):
        #     for record in self:
        #         record.is_expired = record.expiry_date and record.expiry_date < fields.Date.today()

        @api.model_create_multi
        def create(self, vals_list):
            for vals in vals_list:
                if 'number' not in vals:
                    vals['number'] = self.env['ir.sequence'].next_by_code('project.level.required.document') or _("New")
            return super(ProjectLevelRequiredDocument, self).create(vals_list)

        def action_upload_document(self):
            """Action to upload document for this line"""
            self.ensure_one()
            return {
                'name': _('Upload Document'),
                'type': 'ir.actions.act_window',
                'res_model': 'document.upload.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_name': self.document_type_id.name,
                    'default_document_type': 'required',
                    'default_project_id': self.project_id.id,
                    'default_document_line_id': self.id,
                    'default_user_id': self.env.user.id,
                }
            }


    class ProjectLevelDeliverableDocument(models.Model):
        _name = 'project.level.deliverable.document'
        _description = 'Project Level Deliverable Document'
        _order = 'sequence, id'

        project_id = fields.Many2one('project.project', string='Project', required=True, ondelete='cascade')
        document_type_id = fields.Many2one('project.document.type', string='Document Type', required=True)
        document_id = fields.Many2one('documents.document', string='Document', required=True)
        sequence = fields.Integer(string='Sequence', default=10)
        is_required = fields.Boolean(string='Required', default=True)
        is_verified = fields.Boolean(string='Verified', default=False)
        verification_date = fields.Date(string='Verification Date')
        verified_by = fields.Many2one('res.users', string='Verified By')
        expiry_date = fields.Date('Expiry Date')
        reminder_days = fields.Integer('Reminder Days', default=30)
        is_expired = fields.Boolean('Is Expired', default=False)
        number = fields.Char(
            string="Number",
            required=True,
            copy=False,
            readonly=True,
            index=True,
            default=lambda self: _("New"),
        )
        issue_date = fields.Date(
            default=fields.Date.today,
            help="Date when the document was issued",
        )
        attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
        expiration_reminder = fields.Boolean(default=False)
        expiration_reminder_sent = fields.Boolean(default=False)
        document_create_date = fields.Datetime(
            readonly=True,
            string="Document Create Date",
            default=fields.datetime.now(),
        )

        # @api.depends('expiry_date')
        # def _compute_expired(self):
        #     for record in self:
        #         record.is_expired = record.expiry_date and record.expiry_date < fields.Date.today()

        @api.model_create_multi
        def create(self, vals_list):
            for vals in vals_list:
                if 'number' not in vals:
                    vals['number'] = self.env['ir.sequence'].next_by_code('project.level.deliverable.document') or _("New")
            return super(ProjectLevelDeliverableDocument, self).create(vals_list)

        def action_upload_document(self):
            """Action to upload document for this line"""
            self.ensure_one()
            return {
                'name': _('Upload Document'),
                'type': 'ir.actions.act_window',
                'res_model': 'document.upload.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_name': self.document_type_id.name,
                    'default_document_type': 'deliverable',
                    'default_project_id': self.project_id.id,
                    'default_document_line_id': self.id,
                    'default_user_id': self.env.user.id,
                }
            }

# End of disabled models block


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Existing fields (for backward compatibility) ---
    # Comment out legacy field definition from ProjectProject
    # document_type_ids = fields.One2many('project.document.type.line', 'project_id', string='Deliverable Document Types')
    # sale_order_id field is inherited from sale_project, do not redefine
    
    # --- NEW: X_ Fields for Documents Module Integration ---
    x_required_document_ids = fields.One2many(
        'project.required.document', 'x_project_id', string='x_Required Documents')
    x_deliverable_document_ids = fields.One2many(
        'project.deliverable.document', 'x_project_id', string='x_Deliverable Documents')
    
    # --- NEW: X_ Workflow checkboxes for Required Documents ---
    x_required_document_complete = fields.Boolean(string="x_Required Document Complete", default=False)
    x_required_document_confirm = fields.Boolean(string="x_Required Document Confirm", default=False)
    x_required_document_update = fields.Boolean(string="x_Required Document Update", default=False)

    # --- NEW: X_ Workflow checkboxes for Deliverable Documents ---
    x_deliverable_document_complete = fields.Boolean(string="x_Deliverable Document Complete", default=False)
    x_deliverable_document_confirm = fields.Boolean(string="x_Deliverable Document Confirm", default=False)
    x_deliverable_document_update = fields.Boolean(string="x_Deliverable Document Update", default=False)
    
    # --- Documents folder field ---
    documents_folder_id = fields.Many2one(
        'documents.document', string="Folder", copy=False,
        domain="[('type', '=', 'folder')]",
        help="Folder in which all of the documents of this project will be categorized."
    )
    
    def _ensure_project_folder(self):
        """Ensure the project has a documents folder"""
        _logger.info(f"🔧 Ensuring project '{self.name}' has a documents folder")
        
        if not self.documents_folder_id:
            try:
                # Look for existing folder
                existing_folder = self.env['documents.document'].search([
                    ('name', '=', self.name),
                    ('type', '=', 'folder')
                ], limit=1)
                
                if existing_folder:
                    self.documents_folder_id = existing_folder.id
                    _logger.info(f"✅ Found existing folder '{existing_folder.name}' for project '{self.name}'")
                else:
                    # Create new folder
                    new_folder = self.env['documents.document'].create({
                        'name': self.name,
                        'type': 'folder',
                        'company_id': self.company_id.id if self.company_id else False,
                    })
                    self.documents_folder_id = new_folder.id
                    _logger.info(f"✅ Created new documents folder '{new_folder.name}' for project '{self.name}'")
            except Exception as e:
                _logger.error(f"❌ Failed to create documents folder for project {self.name}: {e}")
        else:
            _logger.info(f"✅ Project '{self.name}' already has documents folder '{self.documents_folder_id.name}'")

    # --- Workflow checkboxes for Required Documents ---
    required_document_complete = fields.Boolean(string="Required Document Complete", default=False)
    required_document_confirm = fields.Boolean(string="Required Document Confirm", default=False)
    required_document_update = fields.Boolean(string="Required Document Update", default=False)

    # --- Workflow checkboxes for Deliverable Documents ---
    deliverable_document_complete = fields.Boolean(string="Deliverable Document Complete", default=False)
    deliverable_document_confirm = fields.Boolean(string="Deliverable Document Confirm", default=False)
    deliverable_document_update = fields.Boolean(string="Deliverable Document Update", default=False)

    # --- Workflow checkboxes for Compliance ---
    is_complete_return_compliance = fields.Boolean(string="Compliance Complete", default=False)
    is_confirm_compliance = fields.Boolean(string="Compliance Confirm", default=False)
    is_update_compliance = fields.Boolean(string="Update Compliance", default=False)

    # --- Project-specific fields ---
    return_reason = fields.Text(string="Return Reason")
    return_date = fields.Date(string="Return Date")
    update_reason = fields.Text(string="Update Reason")
    update_date = fields.Date(string="Update Date")

    # --- Partner Related Fields (Compliance) ---
    project_field_ids = fields.One2many(
        "project.res.partner.fields",
        "project_id",
        string="Project Partner Fields",
        copy=False,
    )
    
    # --- Enhanced Partner Fields (Phase 6.1) ---
    legal_entity_type_id = fields.Many2one(
        'legal.entity.type',
        string='Legal Entity Type',
        help='Type of legal entity (FZCO, FZE, LLC, etc.)'
    )

    hand_type_id = fields.Many2one(
        'partner.hand.type',
        string='Hand Type',
        help='Whether partner is a company or individual'
    )

    # Enhanced Partner Information
    trade_license_number = fields.Char(
        string='Trade License Number',
        help='Trade license number for the partner'
    )

    establishment_card_number = fields.Char(
        string='Establishment Card Number',
        help='Establishment card number for the partner'
    )

    visa_number = fields.Char(
        string='Visa Number',
        help='Visa number for the partner'
    )

    emirates_id = fields.Char(
        string='Emirates ID',
        help='Emirates ID for the partner'
    )

    passport_number = fields.Char(
        string='Passport Number',
        help='Passport number for the partner'
    )

    # Status Fields
    is_verified = fields.Boolean(
        string='Verified',
        default=False,
        help='Whether the partner information has been verified'
    )

    verification_date = fields.Date(
        string='Verification Date',
        help='Date when the partner information was verified'
    )

    verified_by = fields.Many2one(
        'res.users',
        string='Verified By',
        help='User who verified the partner information'
    )
    
    # --- Partner Fields Workflow checkboxes ---
    is_complete_partner_fields = fields.Boolean(string="Complete Partner Fields", default=False)
    is_confirm_partner_fields = fields.Boolean(string="Partner Fields Confirm", default=False)
    is_complete_return_partner_fields = fields.Boolean(string="Partner Fields Complete Return", default=False)
    is_second_complete_partner_fields_check = fields.Integer(string="Second Complete Partner Fields Check", default=0)
    is_update_partner_fields = fields.Boolean(string="Update Partner Fields", default=False)
    
    # --- Computed field for partner fields update check ---
    is_update_partner_fields_check = fields.Boolean(string="Update Partner Fields Check", compute="_compute_is_update_partner_fields_check")
    
    # --- Reached Checkpoints ---
    reached_checkpoint_ids = fields.Many2many(
        'reached.checkpoint', 
        string='Reached Checkpoints',
        help='Track checkpoints that have been reached in this project'
    )

    # --- Project Checkpoints ---
    task_checkpoint_ids = fields.One2many('task.checkpoint', 'project_id', string='Project Checkpoints')

    # --- Computed Summary Fields ---
    checkpoint_summary = fields.Text(
        string="Checkpoint Summary", 
        compute='_compute_checkpoint_summary',
        help="Summary of all checkpoint statuses"
    )
    
    @api.depends('is_update_partner_fields')
    def _compute_is_update_partner_fields_check(self):
        for record in self:
            record.is_update_partner_fields_check = record.is_update_partner_fields

    @api.depends('required_document_complete', 'required_document_confirm', 'required_document_update',
                 'deliverable_document_complete', 'deliverable_document_confirm', 'deliverable_document_update',
                 'is_complete_return_compliance', 'is_confirm_compliance', 'is_update_compliance',
                 'is_complete_partner_fields', 'is_confirm_partner_fields', 'is_update_partner_fields',
                 'is_handover_complete')
    def _compute_checkpoint_summary(self):
        """Compute a summary of all checkpoint statuses."""
        for project in self:
            summary = []
            completed_count = 0
            total_required = 4  # Total required checkpoints for completion
            
            # Required Documents
            if project.required_document_complete:
                summary.append("✅ Required Documents Complete")
                completed_count += 1
            elif project.required_document_confirm:
                summary.append("✅ Required Documents Confirmed")
                completed_count += 1
            elif project.required_document_update:
                summary.append("✅ Required Documents Updated")
                completed_count += 1
            else:
                summary.append("⏳ Required Documents: Not Complete")
            
            # Deliverable Documents  
            if project.deliverable_document_complete:
                summary.append("✅ Deliverable Documents Complete")
                completed_count += 1
            elif project.deliverable_document_confirm:
                summary.append("✅ Deliverable Documents Confirmed")
                completed_count += 1
            elif project.deliverable_document_update:
                summary.append("✅ Deliverable Documents Updated")
                completed_count += 1
            else:
                summary.append("⏳ Deliverable Documents: Not Complete")
            
            # Compliance
            if project.is_complete_return_compliance:
                summary.append("✅ Compliance Complete")
                completed_count += 1
            elif project.is_confirm_compliance:
                summary.append("✅ Compliance Confirmed")
                completed_count += 1
            elif project.is_update_compliance:
                summary.append("✅ Compliance Updated")
                completed_count += 1
            else:
                summary.append("⏳ Compliance: Not Complete")
            
            # Partner Fields
            if project.is_complete_partner_fields:
                summary.append("✅ Partner Fields Complete")
                completed_count += 1
            elif project.is_confirm_partner_fields:
                summary.append("✅ Partner Fields Confirmed")
                completed_count += 1
            elif project.is_update_partner_fields:
                summary.append("✅ Partner Fields Updated")
                completed_count += 1
            else:
                summary.append("⏳ Partner Fields: Not Complete")
            
            # Handover (optional)
            if project.is_handover_complete:
                summary.append("✅ Handover Complete")
            
            # Add progress indicator
            progress_percentage = (completed_count / total_required) * 100
            progress_summary = f"\n📊 Progress: {completed_count}/{total_required} checkpoints completed ({progress_percentage:.0f}%)"
            
            if completed_count == total_required:
                progress_summary += "\n🎉 All required checkpoints completed! Project ready for final milestone."
            else:
                remaining = total_required - completed_count
                progress_summary += f"\n⏳ {remaining} checkpoint(s) remaining for project completion."
            
            project.checkpoint_summary = progress_summary + "\n\n" + "\n".join(summary) if summary else _("No checkpoints completed")

    # --- Project Notes (Compliance & Handover) ---
    compliance_notes = fields.Html(
        string="Compliance Notes",
        help="Notes related to compliance requirements and status for this project"
    )
    
    handover_notes = fields.Html(
        string="Handover Notes", 
        help="Notes for project handover including deliverables, access, and instructions"
    )
    
    internal_notes = fields.Html(
        string="Internal Notes",
        help="Internal project notes for team reference"
    )
    
    client_notes = fields.Html(
        string="Client Notes",
        help="Notes visible to client or for client communication"
    )
    
    # --- Handover Status Fields ---
    is_handover_complete = fields.Boolean(
        string="Handover Complete",
        default=False,
        help="Mark when project handover is complete"
    )
    
    handover_date = fields.Date(
        string="Handover Date",
        help="Date when project was handed over to client"
    )
    
    handover_by = fields.Many2one(
        'res.users',
        string="Handed Over By",
        help="User who completed the handover"
    )

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        # Temporarily disable document copying again to isolate transaction issues
        # for project in projects:
        #     # Try to get product templates from sale order lines if available
        #     sale_line_id = project.sale_line_id.id if hasattr(project, 'sale_line_id') and project.sale_line_id else None
        #     product_templates = []
        #     if sale_line_id:
        #         sale_line = self.env['sale.order.line'].browse(sale_line_id)
        #         if sale_line and sale_line.product_id:
        #             product_templates.append(sale_line.product_id.product_tmpl_id)
        #     # Optionally, add logic to get product templates from context if needed
        #     if product_templates:
        #         try:
        #             copy_documents_from_product_to_project(self.env, project, product_templates)
        #         except Exception as e:
        #             # Log the error but don't fail project creation
        #             _logger.warning(f"Failed to copy documents from product template: {e}")
        return projects

    # Re-enable project-level document management methods
    # --- Project-level document management methods ---
    def _validate_x_required_documents_uploaded(self):
        missing_docs = []
        for line in self.x_required_document_ids:
            if getattr(line, 'x_is_required', False):
                has_attachment = False
                if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                    has_attachment = True
                if not has_attachment:
                    attachments = self.env['ir.attachment'].search([
                        ('res_model', '=', line._name),
                        ('res_id', '=', line.id),
                        ('name', '=', line.name)
                    ], limit=1)
                    if attachments:
                        has_attachment = True
                if not has_attachment:
                    missing_docs.append(line.name or 'Unknown Document')
        if missing_docs:
            raise ValidationError(
                "You must upload the following x_ required documents before completing this action:\n- " + "\n- ".join(missing_docs)
            )

    def action_complete_required_documents(self):
        self.ensure_one()
        self._validate_x_required_documents_uploaded()
        self.x_required_document_complete = True
        self.message_post(body=_("✅ x_Required Documents workflow completed"))
        self._create_reached_checkpoint("Required Documents Complete")
        self._check_and_trigger_final_milestone()
        return True

    def action_confirm_required_documents(self):
        self.ensure_one()
        self._validate_x_required_documents_uploaded()
        self.x_required_document_confirm = True
        self.message_post(body=_("✅ x_Required Documents workflow confirmed"))
        self._create_reached_checkpoint("Required Documents Confirmed")
        self._check_and_trigger_final_milestone()
        return True

    def action_update_required_documents(self):
        self.ensure_one()
        self._validate_x_required_documents_uploaded()
        self.x_required_document_update = True
        self.message_post(body=_("✅ x_Required Documents workflow updated"))
        self._create_reached_checkpoint("Required Documents Updated")
        self._check_and_trigger_final_milestone()
        return True

    def action_reset_required_document_complete(self):
        self.ensure_one()
        self.required_document_complete = False  # legacy
        self.x_required_document_complete = False  # x_
        return True

    def action_reset_required_document_confirm(self):
        self.ensure_one()
        self.required_document_confirm = False  # legacy
        self.x_required_document_confirm = False  # x_
        return True

    def action_reset_required_document_update(self):
        self.ensure_one()
        self.required_document_update = False  # legacy
        self.x_required_document_update = False  # x_
        return True

    def action_repeat_required_documents(self):
        """Repeat required documents workflow - reset all states"""
        self.ensure_one()
        
        # SOFT VALIDATION: Check if there are any documents before allowing repeat
        if self.document_required_type_ids:
            # Show confirmation dialog
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Repeat Action'),
                    'default_message': _('⚠️ You are resetting the workflow while documents exist. This will reset all statuses.\n\nDo you want to proceed?'),
                    'default_action_type': 'repeat_required',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No documents exist, proceed directly
        return self._execute_repeat_required_documents()

    def action_return_required_documents(self):
        """Return required documents for review"""
        self.ensure_one()
        
        # Always show confirmation dialog
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.action.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': _('Confirm Return Action'),
                'default_message': _('⚠️ You are returning documents for review. This will reset completion status.\n\nDo you want to proceed?'),
                'default_action_type': 'return_required',
                'default_record_id': self.id,
                'default_record_model': self._name,
            }
        }

    def _execute_repeat_required_documents(self):
        """Execute repeat required documents workflow"""
        self.ensure_one()
        self.required_document_complete = False
        self.required_document_confirm = False
        self.required_document_update = False
        self.message_post(body="🔄 Required documents workflow reset for repetition")
        return {'type': 'ir.actions.act_window_close'}

    def _execute_return_required_documents(self):
        """Execute return required documents workflow"""
        self.ensure_one()
        self.required_document_complete = False
        self.required_document_confirm = False
        self.message_post(body="📤 Required documents returned for review")
        return {'type': 'ir.actions.act_window_close'}

    def _validate_x_deliverable_documents_uploaded(self):
        missing_docs = []
        for line in self.x_deliverable_document_ids:
            if getattr(line, 'x_is_required', False):
                has_attachment = False
                if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                    has_attachment = True
                if not has_attachment:
                    attachments = self.env['ir.attachment'].search([
                        ('res_model', '=', line._name),
                        ('res_id', '=', line.id),
                        ('name', '=', line.name)
                    ], limit=1)
                    if attachments:
                        has_attachment = True
                if not has_attachment:
                    missing_docs.append(line.name or 'Unknown Document')
        if missing_docs:
            raise ValidationError(
                "You must upload the following x_ deliverable documents before completing this action:\n- " + "\n- ".join(missing_docs)
            )

    def action_complete_deliverable_documents(self):
        self.ensure_one()
        self._validate_x_deliverable_documents_uploaded()
        self.x_deliverable_document_complete = True
        self.message_post(body=_("✅ x_Deliverable Documents workflow completed"))
        self._create_reached_checkpoint("Deliverable Documents Complete")
        self._check_and_trigger_final_milestone()
        return True

    def action_confirm_deliverable_documents(self):
        self.ensure_one()
        self._validate_x_deliverable_documents_uploaded()
        self.x_deliverable_document_confirm = True
        self.message_post(body=_("✅ x_Deliverable Documents workflow confirmed"))
        self._create_reached_checkpoint("Deliverable Documents Confirmed")
        self._check_and_trigger_final_milestone()
        return True

    def action_update_deliverable_documents(self):
        self.ensure_one()
        self._validate_x_deliverable_documents_uploaded()
        self.x_deliverable_document_update = True
        self.message_post(body=_("✅ x_Deliverable Documents workflow updated"))
        self._create_reached_checkpoint("Deliverable Documents Updated")
        self._check_and_trigger_final_milestone()
        return True

    def action_reset_deliverable_document_complete(self):
        self.ensure_one()
        self.deliverable_document_complete = False  # legacy
        self.x_deliverable_document_complete = False  # x_
        return True

    def action_reset_deliverable_document_confirm(self):
        self.ensure_one()
        self.deliverable_document_confirm = False  # legacy
        self.x_deliverable_document_confirm = False  # x_
        return True

    def action_reset_deliverable_document_update(self):
        self.ensure_one()
        self.deliverable_document_update = False  # legacy
        self.x_deliverable_document_update = False  # x_
        return True

    def action_repeat_deliverable_documents(self):
        """Repeat deliverable documents workflow - reset all states"""
        self.ensure_one()
        
        # SOFT VALIDATION: Check if there are any documents before allowing repeat
        if self.document_type_ids:
            # Show confirmation dialog
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Repeat Action'),
                    'default_message': _('⚠️ You are resetting the workflow while documents exist. This will reset all statuses.\n\nDo you want to proceed?'),
                    'default_action_type': 'repeat_deliverable',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No documents exist, proceed directly
        return self._execute_repeat_deliverable_documents()

    def action_return_deliverable_documents(self):
        """Return deliverable documents for review"""
        self.ensure_one()
        
        # Always show confirmation dialog
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.action.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': _('Confirm Return Action'),
                'default_message': _('⚠️ You are returning documents for review. This will reset completion status.\n\nDo you want to proceed?'),
                'default_action_type': 'return_deliverable',
                'default_record_id': self.id,
                'default_record_model': self._name,
            }
        }

    def _execute_repeat_deliverable_documents(self):
        """Execute repeat deliverable documents workflow"""
        self.ensure_one()
        self.deliverable_document_complete = False
        self.deliverable_document_confirm = False
        self.deliverable_document_update = False
        self.message_post(body="🔄 Deliverable documents workflow reset for repetition")
        return {'type': 'ir.actions.act_window_close'}

    def _execute_return_deliverable_documents(self):
        """Execute return deliverable documents workflow"""
        self.ensure_one()
        self.deliverable_document_complete = False
        self.deliverable_document_confirm = False
        self.message_post(body="📤 Deliverable documents returned for review")
        return {'type': 'ir.actions.act_window_close'}

    # --- Compliance Action Methods ---
    def action_complete_compliance(self):
        """Complete compliance workflow"""
        self.ensure_one()
        self.is_complete_return_compliance = True
        self.message_post(body=_("✅ Compliance workflow completed"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Compliance Complete")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_confirm_compliance(self):
        """Confirm compliance workflow"""
        self.ensure_one()
        self.is_confirm_compliance = True
        self.message_post(body=_("✅ Compliance workflow confirmed"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Compliance Confirmed")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_update_compliance(self):
        """Update compliance workflow"""
        self.ensure_one()
        self.is_update_compliance = True
        self.message_post(body=_("✅ Compliance workflow updated"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Compliance Updated")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_reset_compliance_complete(self):
        """Reset compliance complete status"""
        self.ensure_one()
        self.is_complete_return_compliance = False
        return True

    def action_reset_compliance_confirm(self):
        """Reset compliance confirm status"""
        self.ensure_one()
        self.is_confirm_compliance = False
        return True

    def action_reset_compliance_update(self):
        """Reset compliance update status"""
        self.ensure_one()
        self.is_update_compliance = False
        return True

    # --- Partner Fields Workflow Methods ---
    def action_complete_partner_fields(self):
        """Complete partner fields workflow"""
        self.ensure_one()
        self.is_complete_partner_fields = True
        self.message_post(body=_("✅ Partner Fields workflow completed"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Partner Fields Complete")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_confirm_partner_fields(self):
        """Confirm partner fields workflow"""
        self.ensure_one()
        self.is_confirm_partner_fields = True
        self.message_post(body=_("✅ Partner Fields workflow confirmed"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Partner Fields Confirmed")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_complete_return_partner_fields(self):
        """Complete return partner fields workflow"""
        self.ensure_one()
        self.is_complete_return_partner_fields = True
        self.message_post(body="✅ Partner fields return completed")
        return True

    def action_update_partner_fields(self):
        """Update partner fields workflow"""
        self.ensure_one()
        self.is_update_partner_fields = True
        self.message_post(body=_("✅ Partner Fields workflow updated"))
        
        # Create reached checkpoint
        self._create_reached_checkpoint("Partner Fields Updated")
        
        # Check if all checkpoints are reached
        self._check_and_trigger_final_milestone()

    def action_reset_partner_fields_complete(self):
        """Reset partner fields complete status"""
        self.ensure_one()
        self.is_complete_partner_fields = False
        return True

    def action_reset_partner_fields_confirm(self):
        """Reset partner fields confirm status"""
        self.ensure_one()
        self.is_confirm_partner_fields = False
        return True

    def action_reset_partner_fields_return(self):
        """Reset partner fields return status"""
        self.ensure_one()
        self.is_complete_return_partner_fields = False
        return True

    def action_reset_partner_fields_update(self):
        """Reset partner fields update status"""
        self.ensure_one()
        self.is_update_partner_fields = False
        return True

    # --- Enhanced Partner Fields Methods (Phase 6.1) ---
    def action_verify_partner(self):
        """Verify the partner information"""
        self.ensure_one()
        if not self.partner_id:
            raise ValidationError(_("No partner found for this project"))
        
        self.write({
            'is_verified': True,
            'verification_date': fields.Date.today(),
            'verified_by': self.env.user.id
        })
        
        self.message_post(
            body=f"Partner information verified by {self.env.user.name}"
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Partner information has been verified.'),
                'type': 'success',
            }
        }

    def action_unverify_partner(self):
        """Unverify the partner information"""
        self.ensure_one()
        
        self.write({
            'is_verified': False,
            'verification_date': False,
            'verified_by': False
        })
        
        self.message_post(
            body=f"Partner information verification removed by {self.env.user.name}"
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Partner information verification has been removed.'),
                'type': 'success',
            }
        }

    def action_validate_legal_entity(self):
        """Validate legal entity information"""
        self.ensure_one()
        
        if not self.legal_entity_type_id:
            raise ValidationError(_("Please select a legal entity type"))
        
        if not self.trade_license_number:
            raise ValidationError(_("Please provide a trade license number"))
        
        # Add validation logic here
        self.message_post(
            body=f"Legal entity validation completed for {self.legal_entity_type_id.name}"
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Legal entity information has been validated.'),
                'type': 'success',
            }
        }

    def action_validate_hand_type(self):
        """Validate hand type information"""
        self.ensure_one()
        
        if not self.hand_type_id:
            raise ValidationError(_("Please select a hand type"))
        
        # Add validation logic here
        self.message_post(
            body=f"Hand type validation completed for {self.hand_type_id.name}"
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Hand type information has been validated.'),
                'type': 'success',
            }
        }

    # --- Project Return/Update Actions ---
    def action_project_return(self):
        """Open project return form with confirmation"""
        self.ensure_one()
        
        # Check if project has any active content that would be affected
        has_documents = bool(self.document_required_type_ids or self.document_type_ids)
        has_tasks = bool(self.task_ids.filtered(lambda t: t.active))
        has_workflow_progress = any([
            self.required_document_complete, self.required_document_confirm, self.required_document_update,
            self.deliverable_document_complete, self.deliverable_document_confirm, self.deliverable_document_update,
            self.is_complete_return_compliance, self.is_confirm_compliance, self.is_update_compliance,
            self.is_complete_partner_fields, self.is_confirm_partner_fields, self.is_update_partner_fields,
        ])
        
        # If project has content, show confirmation
        if has_documents or has_tasks or has_workflow_progress:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Project Return'),
                    'default_message': _('⚠️ This project contains documents, tasks, or workflow progress.\n\nReturning the project will archive it and may affect ongoing work.\n\nDo you want to proceed with the return?'),
                    'default_action_type': 'project_return',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No content to worry about, proceed directly
        return self._execute_project_return()

    def _execute_project_return(self):
        """Execute project return action"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'res_id': self.id,
            'view_id': self.env.ref('project_documents_extension.project_return_form_view').id,
            'target': 'new',
            'context': {
                'default_id': self.id,
                'default_name': self.name,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            }
        }

    def action_project_update(self):
        """Open project update form with confirmation"""
        self.ensure_one()
        
        # Check if project has any active content that would be affected
        has_documents = bool(self.document_required_type_ids or self.document_type_ids)
        has_tasks = bool(self.task_ids.filtered(lambda t: t.active))
        has_workflow_progress = any([
            self.required_document_complete, self.required_document_confirm, self.required_document_update,
            self.deliverable_document_complete, self.deliverable_document_confirm, self.deliverable_document_update,
            self.is_complete_return_compliance, self.is_confirm_compliance, self.is_update_compliance,
            self.is_complete_partner_fields, self.is_confirm_partner_fields, self.is_update_partner_fields,
        ])
        
        # If project has content, show confirmation
        if has_documents or has_tasks or has_workflow_progress:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Project Update'),
                    'default_message': _('⚠️ This project contains documents, tasks, or workflow progress.\n\nUpdating the project may affect ongoing work and document statuses.\n\nDo you want to proceed with the update?'),
                    'default_action_type': 'project_update',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No content to worry about, proceed directly
        return self._execute_project_update()

    def _execute_project_update(self):
        """Execute project update action"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'res_id': self.id,
            'view_id': self.env.ref('project_documents_extension.project_update_fields_form_view').id,
            'target': 'new',
            'context': {
                'default_id': self.id,
                'default_name': self.name,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            }
        }

    def action_process_project_return(self):
        """Process project return - called when return form is saved"""
        self.ensure_one()
        if self.return_reason:
            # Update project status
            self.write({
                'active': False,  # Archive the project
                'return_date': fields.Date.today() if not self.return_date else self.return_date,
            })
            
            # Post message to project chatter
            return_message = _("🔄 Project Returned\n\n")
            return_message += _("📅 Return Date: %s\n") % (self.return_date or fields.Date.today())
            return_message += _("📝 Return Reason: %s\n") % self.return_reason
            return_message += _("👤 Returned By: %s") % self.env.user.name
            
            self.message_post(body=return_message)
            
            # Simple notification without mail.channel
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Project Returned'),
                    'message': _('Project "%s" has been successfully returned.') % self.name,
                    'type': 'success',
                }
            }
        return True

    def action_process_project_update(self):
        """Process project update - called when update form is saved"""
        self.ensure_one()
        if self.update_reason:
            # Update project
            self.write({
                'update_date': fields.Date.today() if not self.update_date else self.update_date,
            })
            
            # Post message to project chatter
            update_message = _("📝 Project Updated\n\n")
            update_message += _("📅 Update Date: %s\n") % (self.update_date or fields.Date.today())
            update_message += _("📝 Update Reason: %s\n") % self.update_reason
            update_message += _("👤 Updated By: %s") % self.env.user.name
            
            self.message_post(body=update_message)
            
            # Simple notification
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Project Updated'),
                    'message': _('Project "%s" has been successfully updated.') % self.name,
                    'type': 'success',
                }
            }
        return True

    def action_trigger_milestone_notification(self, milestone):
        """Trigger milestone notification for this project"""
        self.ensure_one()
        if milestone:
            milestone.send_milestone_notification(self)
            self.message_post(
                body=f"🎯 **Milestone Reached**: {milestone.name}\n\n{milestone.milestone_message or 'Milestone completed successfully.'}",
                message_type='notification'
            )
        return True

    def action_get_milestone_progress(self):
        """Get milestone progress for this project"""
        self.ensure_one()
        
        # Debug: Log that method is called
        _logger.info(f"🎯 action_get_milestone_progress called for project: {self.name}")
        
        milestones = self.milestone_ids
        total_milestones = len(milestones)
        completed_milestones = milestones.filtered(lambda m: m.is_reached)
        completed_count = len(completed_milestones)
        
        # Debug: Log milestone counts
        _logger.info(f"📊 Milestone stats - Total: {total_milestones}, Completed: {completed_count}")
        
        # Calculate progress
        progress_percentage = (completed_count / total_milestones * 100) if total_milestones > 0 else 0
        
        # Build status message
        status_message = f"📊 **Milestone Progress Report**\n\n"
        status_message += f"**Project:** {self.name}\n\n"
        status_message += f"**Progress Summary:**\n"
        status_message += f"• Total Milestones: {total_milestones}\n"
        status_message += f"• Completed: {completed_count}\n"
        status_message += f"• Pending: {total_milestones - completed_count}\n"
        status_message += f"• Completion Rate: {progress_percentage:.0f}%\n\n"
        
        if completed_count > 0:
            status_message += f"✅ **Completed Milestones:**\n"
            for milestone in completed_milestones:
                status_message += f"• {milestone.name}\n"
            status_message += "\n"
        
        if total_milestones - completed_count > 0:
            pending_milestones = milestones.filtered(lambda m: not m.is_reached)
            status_message += f"⏳ **Pending Milestones:**\n"
            for milestone in pending_milestones:
                status_message += f"• {milestone.name}\n"
            status_message += "\n"
        
        if completed_count == total_milestones and total_milestones > 0:
            status_message += "🎉 **All milestones completed! Project is fully finished.**"
        elif total_milestones == 0:
            status_message += "💡 **No milestones found for this project.**\nCreate milestones to track project progress."
        else:
            remaining = total_milestones - completed_count
            status_message += f"📅 **Next Steps:**\nComplete the remaining {remaining} milestone(s) to finish the project."
        
        # Debug: Log the message being sent
        _logger.info(f"📝 Status message: {status_message}")
        
        # Post message to project chatter
        self.message_post(
            body=status_message,
            message_type='notification'
        )
        
        # Debug: Log that we're returning notification
        _logger.info(f"🔔 Returning notification for milestone progress")
        
        # Return notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Milestone Progress Report',
                'message': status_message,
                'type': 'info',
                'sticky': True,
            }
        }

    def action_send_milestone_summary_email(self):
        """Send milestone summary email for this project"""
        self.ensure_one()
        if self.partner_id and self.milestone_ids:
            template = self.env.ref('project_documents_extension.email_template_milestone_summary', raise_if_not_found=False)
            if template:
                template.send_mail(self.id, force_send=True)
                self.message_post(
                    body=f"📧 **Milestone Summary Email Sent** to {self.partner_id.name}",
                    message_type='notification'
                )
        return True

    def action_complete_checkpoint_with_milestone(self, checkpoint_name):
        """Complete a checkpoint and trigger milestone notification if applicable"""
        self.ensure_one()
        
        # Find the checkpoint in task checkpoints
        for task in self.task_ids:
            checkpoint = task.task_checkpoint_ids.filtered(
                lambda c: checkpoint_name in c.checkpoint_ids.mapped('name')
            )[:1]
            
            if checkpoint and checkpoint.milestone_id:
                # Trigger milestone notification
                checkpoint.milestone_id.send_milestone_notification(task)
                
                # Log checkpoint completion
                task.message_post(
                    body=f"✅ **Checkpoint Completed**: {checkpoint_name}\n\nMilestone: {checkpoint.milestone_id.name}",
                    message_type='notification'
                )
                
                return True
        
        return False

    def action_complete_checkpoint_with_milestone_simple(self):
        """Simple action to complete checkpoint with milestone (no parameters)"""
        self.ensure_one()
        
        # Find any task with milestone-linked checkpoints
        for task in self.task_ids:
            checkpoint = task.task_checkpoint_ids.filtered(
                lambda c: c.milestone_id
            )[:1]
            
            if checkpoint:
                checkpoint_name = checkpoint.checkpoint_ids.mapped('name')[0] if checkpoint.checkpoint_ids else "Checkpoint"
                return self.action_complete_checkpoint_with_milestone(checkpoint_name)
        
        # Show notification that no milestone-linked checkpoints found
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'No Milestone Checkpoints',
                'message': 'No checkpoints with linked milestones found for this project.',
                'type': 'warning'
            }
        }

    def action_create_milestone(self):
        """Create a new milestone for this project"""
        self.ensure_one()
        return {
            'name': 'Create Milestone',
            'type': 'ir.actions.act_window',
            'res_model': 'quick.milestone.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_project_id': self.id,
            }
        }

    def _create_reached_checkpoint(self, checkpoint_name):
        """Create a reached checkpoint for the project"""
        self.ensure_one()
        
        # Check if checkpoint already exists
        existing_checkpoint = self.env['reached.checkpoint'].search([
            ('name', '=', checkpoint_name),
            ('project_id', '=', self.id)
        ], limit=1)
        
        if not existing_checkpoint:
            # Create new reached checkpoint
            reached_checkpoint = self.env['reached.checkpoint'].create({
                'name': checkpoint_name,
                'project_id': self.id,
                'reached_date': fields.Date.today(),
                'reached_by': self.env.user.id,
            })
            
            # Add to project's reached checkpoints
            self.reached_checkpoint_ids = [(4, reached_checkpoint.id)]
            
            # Post message about checkpoint reached
            self.message_post(
                body=_("🎯 **Checkpoint Reached**: %s") % checkpoint_name,
                message_type='notification'
            )
            
            return reached_checkpoint
        return existing_checkpoint

    def _check_and_trigger_final_milestone(self):
        """Check if all required checkpoints are reached and trigger final milestone"""
        self.ensure_one()
        
        # Define all required checkpoints for project completion
        required_checkpoints = [
            "Required Documents Complete",
            "Deliverable Documents Complete", 
            "Compliance Complete",
            "Partner Fields Complete",
        ]
        
        # Get all reached checkpoints for this project
        reached_checkpoint_names = self.reached_checkpoint_ids.mapped('name')
        
        # Check if all required checkpoints are reached
        all_reached = all(checkpoint in reached_checkpoint_names for checkpoint in required_checkpoints)
        
        if all_reached:
            # Create final milestone
            final_milestone = self._create_final_milestone()
            
            # Post completion message
            self.message_post(
                body=_("🏆 **PROJECT COMPLETED!** All required checkpoints have been reached. Final milestone created: %s") % final_milestone.name,
                message_type='notification'
            )
            
            # Send completion notification
            self._send_project_completion_notification()
            
            return final_milestone
        
        return False

    def _create_final_milestone(self):
        """Create the final milestone for project completion"""
        self.ensure_one()
        
        # Create final milestone
        final_milestone = self.env['project.milestone'].create({
            'name': f"Project Completion - {self.name}",
            'project_id': self.id,
            'deadline': fields.Date.today(),
            'milestone_message': f"🎉 **PROJECT COMPLETED!**\n\nAll required checkpoints have been reached:\n" + 
                               "\n".join([f"✅ {checkpoint}" for checkpoint in self.reached_checkpoint_ids.mapped('name')]),
            'is_reached': True,
        })
        
        return final_milestone

    def _send_project_completion_notification(self):
        """Send notification about project completion"""
        self.ensure_one()
        
        # Get completion email template
        completion_template = self.env['mail.template'].search([
            ('name', '=', 'Project Completion Notification')
        ], limit=1)
        
        if completion_template:
            try:
                completion_template.send_mail(self.id, force_send=True)
            except Exception as e:
                _logger.error(f"Failed to send project completion email: {e}")
        
        # Also send internal notification
        self.message_post(
            body=_("📧 Project completion notification sent to stakeholders"),
            message_type='notification'
        )

    def action_check_project_completion(self):
        """Manually check if project is ready for completion"""
        self.ensure_one()
        
        # Check current checkpoint status
        reached_checkpoints = self.reached_checkpoint_ids.mapped('name')
        
        # Define required checkpoints with descriptions
        required_checkpoints = {
            "Required Documents Complete": "Complete the Required Documents workflow",
            "Deliverable Documents Complete": "Complete the Deliverable Documents workflow", 
            "Compliance Complete": "Complete the Compliance workflow",
            "Partner Fields Complete": "Complete the Partner Fields workflow",
        }
        
        # Check which checkpoints are missing
        missing_checkpoints = []
        for checkpoint, description in required_checkpoints.items():
            if checkpoint not in reached_checkpoints:
                missing_checkpoints.append(f"• {checkpoint}: {description}")
        
        if missing_checkpoints:
            # Show specific missing checkpoints
            missing_list = "\n".join(missing_checkpoints)
            self.message_post(
                body=_("⚠️ **Project Not Ready for Completion**\n\nMissing checkpoints:\n%s\n\nPlease complete all required workflows first.") % missing_list,
                message_type='notification'
            )
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Project Not Complete',
                    'message': f'Missing {len(missing_checkpoints)} checkpoints:\n\n{missing_list}',
                    'type': 'warning',
                    'sticky': True,
                }
            }
        else:
            # Trigger final milestone
            final_milestone = self._check_and_trigger_final_milestone()
            
            if final_milestone:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Project Completed!',
                        'message': f'All checkpoints reached! Final milestone created: {final_milestone.name}',
                        'type': 'success'
                    }
                }
        
        return True

    def action_get_checkpoint_status(self):
        """Get a quick overview of checkpoint status"""
        self.ensure_one()
        
        reached_checkpoints = self.reached_checkpoint_ids.mapped('name')
        
        # Define required checkpoints with descriptions
        required_checkpoints = {
            "Required Documents Complete": "Complete the Required Documents workflow",
            "Deliverable Documents Complete": "Complete the Deliverable Documents workflow", 
            "Compliance Complete": "Complete the Compliance workflow",
            "Partner Fields Complete": "Complete the Partner Fields workflow",
        }
        
        # Check status
        completed_count = 0
        status_details = []
        
        for checkpoint, description in required_checkpoints.items():
            if checkpoint in reached_checkpoints:
                status_details.append(f"✅ {checkpoint}")
                completed_count += 1
            else:
                status_details.append(f"⏳ {checkpoint}: {description}")
        
        progress_percentage = (completed_count / len(required_checkpoints)) * 100
        
        status_message = f"📊 Checkpoint Status Overview:\n\n"
        status_message += f"Progress: {completed_count}/{len(required_checkpoints)} completed ({progress_percentage:.0f}%)\n\n"
        status_message += "\n".join(status_details)
        
        if completed_count == len(required_checkpoints):
            status_message += "\n\n🎉 All checkpoints completed! Project ready for final milestone."
        else:
            remaining = len(required_checkpoints) - completed_count
            status_message += f"\n\n⏳ {remaining} checkpoint(s) remaining for project completion."
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Checkpoint Status',
                'message': status_message,
                'type': 'info',
                'sticky': True,
            }
        }

    def action_test_button(self):
        """Simple test method to verify button is working"""
        self.ensure_one()
        
        _logger.info(f"🧪 Test button clicked for project: {self.name}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Test Button',
                'message': f'Test button works! Project: {self.name}',
                'type': 'success',
                'sticky': True,
            }
        }
    
    def action_debug_smart_documents(self):
        """Debug method to test smart document creation"""
        self.ensure_one()
        
        if not self.sale_line_id or not self.sale_line_id.order_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Debug Error'),
                    'message': _('No sale order found for this project!'),
                    'type': 'warning',
                }
            }
        
        try:
            document_service = self.env['project.document.service']
            debug_info = document_service.debug_smart_documents(self.id, self.sale_line_id.order_id.id)
            
            # Format debug info for display
            debug_message = f"""
            <b>Smart Document Debug Info:</b><br/>
            <b>Project:</b> {debug_info['project_name']}<br/>
            <b>Sale Order:</b> {debug_info['sale_order_name']}<br/>
            <b>Workflow Products:</b> {len(debug_info['workflow_products'])}<br/>
            <b>Existing Documents:</b><br/>
            • Deliverable: {debug_info['existing_documents']['deliverable']}<br/>
            • Required: {debug_info['existing_documents']['required']}<br/>
            """
            
            if debug_info['workflow_products']:
                debug_message += "<b>Product Details:</b><br/>"
                for product in debug_info['workflow_products']:
                    debug_message += f"• {product['name']} ({product['template_name']})<br/>"
                    debug_message += f"  - Deliverable docs: {product['deliverable_docs']}<br/>"
                    debug_message += f"  - Required docs: {product['required_docs']}<br/>"
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Smart Document Debug'),
                    'message': debug_message,
                    'type': 'info',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Debug Error'),
                    'message': f'Error during debug: {str(e)}',
                                    'type': 'danger',
            }
        }
    
    def action_convert_all_attachments_to_documents(self):
        """
        Convert all x_ document attachments to documents in the project folder.
        """
        self.ensure_one()
        for line in self.x_deliverable_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        for line in self.x_required_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'All x_ document attachments converted to documents in project folder.',
                'type': 'success',
            }
        }
    
    def action_test_attachment_conversion(self):
        """
        Test conversion of all x_ document attachments to documents in the project folder.
        """
        self.ensure_one()
        for line in self.x_deliverable_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        for line in self.x_required_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'All x_ document attachments test-converted to documents in project folder.',
                'type': 'success',
            }
        }
    
    def action_force_attachment_conversion(self):
        """
        Force conversion of all x_ document attachments to documents in the project folder.
        """
        self.ensure_one()
        for line in self.x_deliverable_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        for line in self.x_required_document_ids:
            if hasattr(line, 'x_attachment_ids') and line.x_attachment_ids:
                line.action_convert_x_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'All x_ document attachments force-converted to documents in project folder.',
                'type': 'success',
            }
        }


class ProjectTask(models.Model):
    _inherit = 'project.task'

    document_required_type_ids = fields.One2many(
        'project.document.required.line', 'task_id', string='Required Document Types')
    document_type_ids = fields.One2many(
        'project.document.type.line', 'task_id', string='Deliverable Document Types')

    # --- NEW: X_ Fields for Documents Module Integration ---
    x_required_document_ids = fields.One2many(
        'project.required.document', 'x_task_id', string='x_Required Documents')
    x_deliverable_document_ids = fields.One2many(
        'project.deliverable.document', 'x_task_id', string='x_Deliverable Documents')

    # --- Checkpoints Field ---
    task_checkpoint_ids = fields.One2many('task.checkpoint', 'task_id', string='Checkpoints')

    # Task-level workflow fields (matching original pattern)
    required_document_complete = fields.Boolean(string="Required Document Complete", default=False)
    required_document_confirm = fields.Boolean(string="Required Document Confirm", default=False)
    required_document_update = fields.Boolean(string="Required Document Update", default=False)
    
    deliverable_document_complete = fields.Boolean(string="Deliverable Document Complete", default=False)
    deliverable_document_confirm = fields.Boolean(string="Deliverable Document Confirm", default=False)
    deliverable_document_update = fields.Boolean(string="Deliverable Document Update", default=False)
    
    # --- NEW: X_ Task-level workflow fields ---
    x_required_document_complete = fields.Boolean(string="x_Required Document Complete", default=False)
    x_required_document_confirm = fields.Boolean(string="x_Required Document Confirm", default=False)
    x_required_document_update = fields.Boolean(string="x_Required Document Update", default=False)
    
    x_deliverable_document_complete = fields.Boolean(string="x_Deliverable Document Complete", default=False)
    x_deliverable_document_confirm = fields.Boolean(string="x_Deliverable Document Confirm", default=False)
    x_deliverable_document_update = fields.Boolean(string="x_Deliverable Document Update", default=False)

    # Task-level workflow action methods (matching original pattern)
    def action_complete_required_documents(self):
        """Complete required documents for task"""
        self.ensure_one()
        self.required_document_complete = True
        self.message_post(body="✅ Required documents marked as complete")
        return True

    def action_confirm_required_documents(self):
        """Confirm required documents for task"""
        self.ensure_one()
        self.required_document_confirm = True
        self.message_post(body="✅ Required documents completion confirmed")
        return True

    def action_update_required_documents(self):
        """Update required documents for task"""
        self.ensure_one()
        self.required_document_update = True
        self.message_post(body="🔄 Required documents marked for update")
        return True

    def action_reset_required_document_complete(self):
        """Reset required document complete status"""
        self.ensure_one()
        self.required_document_complete = False
        return True

    def action_reset_required_document_confirm(self):
        """Reset required document confirm status"""
        self.ensure_one()
        self.required_document_confirm = False
        return True

    def action_reset_required_document_update(self):
        """Reset required document update status"""
        self.ensure_one()
        self.required_document_update = False
        return True

    def action_repeat_required_documents(self):
        """Repeat required documents workflow - reset all states"""
        self.ensure_one()
        
        # SOFT VALIDATION: Check if there are any documents before allowing repeat
        if self.document_required_type_ids:
            # Show confirmation dialog
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Repeat Action'),
                    'default_message': _('⚠️ You are resetting the workflow while documents exist. This will reset all statuses.\n\nDo you want to proceed?'),
                    'default_action_type': 'repeat_required',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No documents exist, proceed directly
        return self._execute_repeat_required_documents()

    def action_return_required_documents(self):
        """Return required documents for review"""
        self.ensure_one()
        
        # Always show confirmation dialog
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.action.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': _('Confirm Return Action'),
                'default_message': _('⚠️ You are returning documents for review. This will reset completion status.\n\nDo you want to proceed?'),
                'default_action_type': 'return_required',
                'default_record_id': self.id,
                'default_record_model': self._name,
            }
        }

    def _execute_repeat_required_documents(self):
        """Execute repeat required documents workflow"""
        self.ensure_one()
        self.required_document_complete = False
        self.required_document_confirm = False
        self.required_document_update = False
        self.message_post(body="🔄 Required documents workflow reset for repetition")
        return {'type': 'ir.actions.act_window_close'}

    def _execute_return_required_documents(self):
        """Execute return required documents workflow"""
        self.ensure_one()
        self.required_document_complete = False
        self.required_document_confirm = False
        self.message_post(body="📤 Required documents returned for review")
        return {'type': 'ir.actions.act_window_close'}

    def action_complete_deliverable_documents(self):
        """Complete deliverable documents for task"""
        self.ensure_one()
        self.deliverable_document_complete = True
        self.message_post(body="✅ Deliverable documents marked as complete")
        return True

    def action_confirm_deliverable_documents(self):
        """Confirm deliverable documents for task"""
        self.ensure_one()
        self.deliverable_document_confirm = True
        self.message_post(body="✅ Deliverable documents completion confirmed")
        return True

    def action_update_deliverable_documents(self):
        """Update deliverable documents for task"""
        self.ensure_one()
        self.deliverable_document_update = True
        self.message_post(body="🔄 Deliverable documents marked for update")
        return True

    def action_reset_deliverable_document_complete(self):
        """Reset deliverable document complete status"""
        self.ensure_one()
        self.deliverable_document_complete = False
        return True

    def action_reset_deliverable_document_confirm(self):
        """Reset deliverable document confirm status"""
        self.ensure_one()
        self.deliverable_document_confirm = False
        return True

    def action_reset_deliverable_document_update(self):
        """Reset deliverable document update status"""
        self.ensure_one()
        self.deliverable_document_update = False
        return True

    def action_repeat_deliverable_documents(self):
        """Repeat deliverable documents workflow - reset all states"""
        self.ensure_one()
        
        # SOFT VALIDATION: Check if there are any documents before allowing repeat
        if self.document_type_ids:
            # Show confirmation dialog
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'document.action.confirmation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_title': _('Confirm Repeat Action'),
                    'default_message': _('⚠️ You are resetting the workflow while documents exist. This will reset all statuses.\n\nDo you want to proceed?'),
                    'default_action_type': 'repeat_deliverable',
                    'default_record_id': self.id,
                    'default_record_model': self._name,
                }
            }
        
        # No documents exist, proceed directly
        return self._execute_repeat_deliverable_documents()

    def action_return_deliverable_documents(self):
        """Return deliverable documents for review"""
        self.ensure_one()
        
        # Always show confirmation dialog
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.action.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_title': _('Confirm Return Action'),
                'default_message': _('⚠️ You are returning documents for review. This will reset completion status.\n\nDo you want to proceed?'),
                'default_action_type': 'return_deliverable',
                'default_record_id': self.id,
                'default_record_model': self._name,
            }
        }

    def _execute_repeat_deliverable_documents(self):
        """Execute repeat deliverable documents workflow"""
        self.ensure_one()
        self.deliverable_document_complete = False
        self.deliverable_document_confirm = False
        self.deliverable_document_update = False
        self.message_post(body="🔄 Deliverable documents workflow reset for repetition")
        return {'type': 'ir.actions.act_window_close'}

    def _execute_return_deliverable_documents(self):
        """Execute return deliverable documents workflow"""
        self.ensure_one()
        self.deliverable_document_complete = False
        self.deliverable_document_confirm = False
        self.message_post(body="📤 Deliverable documents returned for review")
        return {'type': 'ir.actions.act_window_close'}



    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            project = task.project_id
            if project:
                try:
                    copy_documents_from_project_to_task(task.env, task, project)
                except Exception as e:
                    # Log the error but don't fail task creation
                    _logger.warning(f"Failed to copy documents from project to task: {e}")
        return tasks

    def action_copy_checkpoints_from_template(self):
        """Manual action to copy checkpoints from product task template"""
        for task in self:
            if task.project_id and task.project_id.sale_order_id:
                # Find matching product task template
                sale_order = task.project_id.sale_order_id
                for line in sale_order.order_line:
                    if line.product_id.service_tracking == 'new_workflow':
                        for template in line.product_id.product_tmpl_id.task_template_ids:
                            if template.name == task.name:
                                try:
                                    # Clear existing checkpoints first
                                    task.task_checkpoint_ids.unlink()
                                    # Copy from template
                                    copy_checkpoints_from_template_to_task(task.env, task, template)
                                    task.message_post(body=f"Checkpoints copied from template: {template.name}")
                                    return {
                                        'type': 'ir.actions.client',
                                        'tag': 'display_notification',
                                        'params': {
                                            'title': 'Success',
                                            'message': f'Checkpoints copied from template: {template.name}',
                                            'type': 'success',
                                            'sticky': False,
                                        }
                                    }
                                except Exception as e:
                                    return {
                                        'type': 'ir.actions.client',
                                        'tag': 'display_notification',
                                        'params': {
                                            'title': 'Error',
                                            'message': f'Failed to copy checkpoints: {str(e)}',
                                            'type': 'danger',
                                            'sticky': True,
                                        }
                                    }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Temporarily disable computed fields to isolate transaction issues
    # project_ids = fields.Many2many('project.project', compute='_compute_project_ids', string='Projects', store=False)
    # project_count = fields.Integer(string='Number of Projects', compute='_compute_project_ids', store=False)

    # def _compute_project_ids(self):
    #     is_project_manager = self.env.user.has_group('project.group_project_manager')
    #     projects = self.env['project.project'].search([
    #         ('sale_order_id', 'in', self.ids)
    #     ])
    #     projects_per_so = defaultdict(lambda: self.env['project.project'])
    #     for project in projects:
    #         projects_per_so[project.sale_order_id.id] |= project

    #     for order in self:
    #         # Fetch projects from various sources
    #         projects = order.order_line.mapped('product_id.project_id')
    #         projects |= order.order_line.mapped('project_id')
    #         projects |= projects_per_so[order.id or order._origin.id]
    #         # Restrict projects if user is not a project manager
    #         if not is_project_manager:
    #             projects = projects._filter_access_rules('read')
    #         order.project_ids = projects
    #         order.project_count = len(projects)

    def action_confirm(self):
        _logger.info(f"🚀 ACTION_CONFIRM called for sale order: {self.name} (ID: {self.id})")
        res = super().action_confirm()
        # Re-enable project creation but keep task creation disabled
        _logger.info(f"🚀 About to call _create_tasks_from_templates for order: {self.name}")
        self._create_tasks_from_templates()
        return res

    def _create_tasks_from_templates(self):
        for order in self:
            try:
                _logger.info(f"🔍 Processing sale order: {order.name} (ID: {order.id})")
                
                all_workflow_products = order.order_line.mapped('product_id').filtered(
                    lambda p: p.service_tracking == 'new_workflow'
                )
                _logger.info(f"🔍 Found {len(all_workflow_products)} products with service_tracking='new_workflow':")
                for product in all_workflow_products:
                    _logger.info(f"  - {product.name} (ID: {product.id}, Service Tracking: {product.service_tracking})")
                
                if not all_workflow_products:
                    _logger.info(f"❌ No workflow products found for order {order.name}, skipping")
                    continue
                
                # Find or create project for this order
                # Fix: Use sale_line_id.order_id instead of sale_order_id
                projects = self.env['project.project'].search([('sale_line_id.order_id', '=', order.id)])
                _logger.info(f"🔍 Found {len(projects)} existing projects for order {order.name}")
                
                if not projects:
                    _logger.info(f"🔨 Creating new project for order {order.name}")
                    # Pass context for document propagation
                    ctx = self.env.context.copy()
                    if order.order_line:
                        ctx['default_sale_order_line_id'] = order.order_line[0].id
                    project = self.env["project.project"].with_context(ctx).create({
                        "name": f"{order.name} - {order.partner_id.name}",
                        "sale_line_id": order.order_line[0].id if order.order_line else False,
                        "user_id": order.user_id.id,
                        "partner_id": order.partner_id.id,
                    })
                    projects = project
                    _logger.info(f"✅ Created project: {project.name} (ID: {project.id})")
                    
                    # Copy documents from product templates to project using Enhanced Document Service
                    try:
                        _logger.info(f"🔧 Using Enhanced Document Service to copy documents")
                        document_service = self.env['project.document.service']
                        documents_created = document_service.create_smart_documents(project, order)
                        _logger.info(f"📋 Enhanced Document service results: {documents_created}")
                        
                        # Post results to the project
                        project.message_post(
                            body=f"Enhanced Smart Document Service Results:<br/>"
                                 f"• Created {documents_created.get('deliverable', 0)} deliverable document lines<br/>"
                                 f"• Created {documents_created.get('required', 0)} required document lines<br/>"
                                 f"• Linked {documents_created.get('existing_linked', 0)} existing documents<br/>"
                                 f"• Prevented {documents_created.get('duplicates_prevented', 0)} duplicates<br/>"
                                 f"• Milestone-based: {documents_created.get('milestone_based', 0)}"
                        )
                    except Exception as e:
                        _logger.error(f"❌ Failed to use enhanced document service: {e}")
                        import traceback
                        _logger.error(f"Full traceback: {traceback.format_exc()}")
                else:
                    _logger.info(f"📁 Using existing projects: {[p.name for p in projects]}")
                    
                # Re-enable task creation
                # Create tasks for each project using the service
                _logger.info(f"🔨 Creating tasks for {len(projects)} projects")
                for project in projects:
                    _logger.info(f"  Processing project: {project.name}")
                    for product in all_workflow_products:
                        _logger.info(f"    Processing product: {product.name}")
                        if product.product_tmpl_id.task_template_ids:
                            _logger.info(f"      Found {len(product.product_tmpl_id.task_template_ids)} task templates")
                            for template in product.product_tmpl_id.task_template_ids:
                                try:
                                    task = self.env['project.task'].create({
                                        'name': template.name,
                                        'project_id': project.id,
                                        'description': template.description,
                                        'user_ids': [(6, 0, template.user_ids.ids)],
                                        'stage_id': template.stage_id.id if template.stage_id else False,
                                        'allocated_hours': template.planned_hours,
                                        'priority': template.priority,
                                    })
                                    _logger.info(f"      ✅ Created task: {task.name} (ID: {task.id})")
                                    
                                    # Copy checkpoints from template to task
                                    try:
                                        copy_checkpoints_from_template_to_task(task.env, task, template)
                                        _logger.info(f"      📋 Copied checkpoints from template to task: {task.name}")
                                    except Exception as checkpoint_error:
                                        _logger.warning(f"      ⚠️ Failed to copy checkpoints for task {task.name}: {checkpoint_error}")
                                    
                                    # Copy documents from project to task with enhanced duplicate prevention
                                    try:
                                        document_service = self.env['project.document.service']
                                        copy_stats = document_service.copy_documents_from_project_to_task(task, project)
                                        _logger.info(f"      📋 Document copy stats for task {task.name}: {copy_stats}")
                                    except Exception as doc_error:
                                        _logger.warning(f"      ⚠️ Failed to copy documents for task {task.name}: {doc_error}")
                                except Exception as e:
                                    _logger.warning(f"      ❌ Failed to create task from template {template.name}: {e}")
                                    continue
                        else:
                            _logger.info(f"      No task templates found for product {product.name}")
            except Exception as e:
                _logger.error(f"❌ Failed to create projects from templates for order {order.name}: {e}")
                import traceback
                _logger.error(f"Full traceback: {traceback.format_exc()}")
                continue 


class ReachedCheckpoint(models.Model):
    _name = 'reached.checkpoint'
    _description = 'Reached Checkpoint'
    _order = 'reached_date desc, id desc'

    name = fields.Char(string='Checkpoint Name', required=True)
    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade')
    reached_date = fields.Date(string='Reached Date', default=fields.Date.today)
    reached_by = fields.Many2one('res.users', string='Reached By', default=lambda self: self.env.user)
    checkpoint_type = fields.Selection([
        ('document', 'Document'),
        ('compliance', 'Compliance'),
        ('partner', 'Partner Fields'),
        ('milestone', 'Milestone'),
        ('custom', 'Custom')
    ], string='Checkpoint Type', default='custom')
    description = fields.Text(string='Description')
    is_final = fields.Boolean(string='Final Checkpoint', default=False, 
                             help='Mark as final checkpoint for project completion')
    
    @api.model
    def create(self, vals):
        """Override create to set checkpoint type based on name"""
        if 'name' in vals:
            name = vals['name'].lower()
            if 'document' in name:
                vals['checkpoint_type'] = 'document'
            elif 'compliance' in name:
                vals['checkpoint_type'] = 'compliance'
            elif 'partner' in name:
                vals['checkpoint_type'] = 'partner'
            elif 'milestone' in name:
                vals['checkpoint_type'] = 'milestone'
        
        return super().create(vals)