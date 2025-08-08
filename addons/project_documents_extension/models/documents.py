from odoo import _, api, fields, models
import logging

_logger = logging.getLogger(__name__)


class DocumentsDocument(models.Model):
    _inherit = 'documents.document'
    
    def _auto_assign_to_project_folder(self):
        """Automatically assign documents to project folders based on res_model and res_id"""
        for document in self:
            _logger.info(f"🔍 Checking document '{document.name}' (res_model='{document.res_model}', res_id={document.res_id})")
            
            if document.res_model == 'project.project' and document.res_id:
                try:
                    project = self.env['project.project'].browse(document.res_id)
                    if project.exists():
                        _logger.info(f"📁 Found project '{project.name}', ensuring it has a folder")
                        
                        # Ensure project has a folder
                        project._ensure_project_folder()
                        
                        # Move document to project folder if not already there
                        if project.documents_folder_id:
                            if document.folder_id != project.documents_folder_id:
                                old_folder = document.folder_id.name if document.folder_id else 'None'
                                document.folder_id = project.documents_folder_id.id
                                _logger.info(f"✅ Moved document '{document.name}' from folder '{old_folder}' to project folder '{project.name}'")
                            else:
                                _logger.info(f"✅ Document '{document.name}' already in correct project folder '{project.name}'")
                        else:
                            _logger.warning(f"⚠️ Project '{project.name}' has no documents folder")
                    else:
                        _logger.warning(f"⚠️ Project with ID {document.res_id} does not exist")
                except Exception as e:
                    _logger.error(f"❌ Failed to assign document {document.name} to project folder: {e}")
            else:
                _logger.info(f"ℹ️ Document '{document.name}' is not linked to a project (res_model='{document.res_model}', res_id={document.res_id})")
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to automatically assign documents to project folders"""
        documents = super().create(vals_list)
        _logger.info(f"🔧 Created {len(documents)} documents, now assigning to project folders")
        documents._auto_assign_to_project_folder()
        return documents
    
    def write(self, vals):
        """Override write to handle folder assignment when res_model/res_id changes"""
        result = super().write(vals)
        
        # If res_model or res_id changed, reassign to project folder
        if 'res_model' in vals or 'res_id' in vals:
            self._auto_assign_to_project_folder()
        
        return result

    @api.onchange('x_project_id', 'x_task_id')
    def _onchange_project_auto_assign_folder(self):
        """Automatically assign project folder when project or task changes"""
        for record in self:
            if record.x_project_id or record.x_task_id:
                record._auto_assign_project_folder() 


class ProjectRequiredDocument(models.Model):
    _name = 'project.required.document'
    _inherits = {'documents.document': 'document_id'}
    _description = 'Required Document for Project'

    document_id = fields.Many2one('documents.document', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', ondelete='cascade')
    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    deadline = fields.Date(string='Deadline')
    notes = fields.Text(string='Notes')
    name = fields.Char(related='document_id.name', string='Name', store=False, readonly=False)
    x_project_id = fields.Many2one('project.project', string='x_Project', ondelete='cascade')
    x_task_id = fields.Many2one('project.task', string='x_Task', ondelete='cascade')
    x_product_tmpl_id = fields.Many2one('product.template', string='x_Product Template', ondelete='cascade')
    x_document_type_id = fields.Many2one('project.document.type', string='x_Document Type')
    x_document_id = fields.Many2one('documents.document', string='x_Document')
    x_is_required = fields.Boolean(string='x_Required', default=False)
    x_expiry_date = fields.Date('x_Expiry Date')
    x_reminder_days = fields.Integer('x_Reminder Days', default=30)
    x_is_expired = fields.Boolean('x_Is Expired', default=False)
    x_is_verify = fields.Boolean('x_Is Verified', default=False)
    x_number = fields.Char(
        string="x_Number",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    x_issue_date = fields.Date(
        default=fields.Date.today,
        help="x_Date when the document was issued",
    )
    x_attachment_ids = fields.Many2many('ir.attachment', string='x_Attachments')
    x_expiration_reminder = fields.Boolean(default=False)
    x_expiration_reminder_sent = fields.Boolean(default=False)
    x_document_create_date = fields.Datetime(
        readonly=True,
        string="x_Document Create Date",
        default=fields.datetime.now(),
    )
    attachment_id = fields.Many2one('ir.attachment', related='document_id.attachment_id', string='Attachment', store=False, readonly=False)
    project_folder_id = fields.Many2one(
        'documents.document', 
        string='Project Folder',
        domain="[('type', '=', 'folder')]",
        help="Folder in documents where this document will be stored"
    )
    
    # Computed field for dynamic name generation
    x_computed_name = fields.Char(
        string='x_Computed Name',
        compute='_compute_x_name',
        store=True,
        help='Dynamically generated name based on document type and template'
    )

    def _auto_assign_project_folder(self):
        """Automatically assign project folder to the document"""
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            _logger.info(f"[AUTO_FOLDER] Record {record.id}: project={getattr(project, 'name', 'None')}, has_folder={bool(project and project.documents_folder_id)}, current_folder={getattr(record.project_folder_id, 'name', 'None')}")
            if project and project.documents_folder_id and not record.project_folder_id:
                record.project_folder_id = project.documents_folder_id.id
                _logger.info(f"[AUTO_FOLDER] ✅ Assigned folder '{project.documents_folder_id.name}' to record {record.id}")
            elif not project:
                _logger.warning(f"[AUTO_FOLDER] ⚠️ No project found for record {record.id}")
            elif not project.documents_folder_id:
                _logger.warning(f"[AUTO_FOLDER] ⚠️ Project '{project.name}' has no documents folder")
            elif record.project_folder_id:
                _logger.info(f"[AUTO_FOLDER] ℹ️ Record {record.id} already has folder '{record.project_folder_id.name}'")

    def _copy_attachments_to_project_folder(self):
        """Copy attachments to the project's documents folder"""
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            if not project or not project.documents_folder_id:
                _logger.warning(f"[COPY_ATTACHMENTS] ⚠️ No project or project folder found for record {record.id}")
                continue
            
            if not record.x_attachment_ids:
                _logger.info(f"[COPY_ATTACHMENTS] ℹ️ No attachments to copy for record {record.id}")
                continue
            
            _logger.info(f"[COPY_ATTACHMENTS] 📎 Copying {len(record.x_attachment_ids)} attachments to project folder '{project.documents_folder_id.name}'")
            
            for attachment in record.x_attachment_ids:
                try:
                    # Check if attachment is already in the project folder
                    existing_doc = self.env['documents.document'].search([
                        ('attachment_id', '=', attachment.id),
                        ('folder_id', '=', project.documents_folder_id.id)
                    ], limit=1)
                    
                    if existing_doc:
                        _logger.info(f"[COPY_ATTACHMENTS] ℹ️ Attachment '{attachment.name}' already exists in project folder")
                        continue
                    
                    # Create a new document in the project folder
                    new_doc = self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'folder_id': project.documents_folder_id.id,
                        'company_id': project.company_id.id,
                        'type': 'binary' if attachment.mimetype.startswith('image/') else 'url',
                    })
                    
                    _logger.info(f"[COPY_ATTACHMENTS] ✅ Successfully copied attachment '{attachment.name}' to project folder")
                    
                except Exception as e:
                    _logger.error(f"[COPY_ATTACHMENTS] ❌ Failed to copy attachment '{attachment.name}': {e}")

    @api.onchange('x_attachment_ids')
    def _onchange_attachments_copy_to_folder(self):
        """Trigger when attachments are added to copy them to project folder"""
        if self.x_attachment_ids:
            _logger.info(f"[ONCHANGE_ATTACHMENTS] 📎 Attachments changed for record {self.id}, will copy to project folder")
            # Note: onchange doesn't persist changes, so we'll handle this in write method

    @api.depends('x_document_type_id', 'x_product_tmpl_id')
    def _compute_x_name(self):
        """Compute dynamic name based on document type and template ID"""
        for record in self:
            if record.x_document_type_id and record.x_product_tmpl_id:
                doc_type_name = record.x_document_type_id.name or ''
                template_name = record.x_product_tmpl_id.name or ''
                template_id = record.x_product_tmpl_id.id
                record.x_computed_name = f"{doc_type_name} - {template_name} (ID: {template_id})"
            elif record.x_document_type_id:
                record.x_computed_name = f"{record.x_document_type_id.name} - Document"
            else:
                record.x_computed_name = "Document"

    @api.depends('x_expiry_date')
    def x_compute_expired(self):
        try:
            today = fields.Date.today()
            for record in self:
                try:
                    if record.x_expiry_date:
                        is_expired = record.x_expiry_date < today
                        record.x_is_expired = is_expired
                    else:
                        record.x_is_expired = False
                except Exception:
                    record.x_is_expired = False
        except Exception:
            for record in self:
                record.x_is_expired = False

    def x_action_numbers(self):
        docs = self.env[self._name].sudo().search([])
        for doc in docs:
            doc.x_number = self.env['ir.sequence'].next_by_code(self._name) or _(u"New")

    @api.model_create_multi
    def x_create(self, vals_list):
        for vals in vals_list:
            if 'x_number' not in vals:
                vals['x_number'] = self.env['ir.sequence'].next_by_code(self._name) or _(u"New")
            # Set product_tmpl_id from context if available
            if 'product_tmpl_id' not in vals and self.env.context.get('default_product_tmpl_id'):
                vals['product_tmpl_id'] = self.env.context['default_product_tmpl_id']
            if 'x_product_tmpl_id' not in vals and self.env.context.get('default_product_tmpl_id'):
                vals['x_product_tmpl_id'] = self.env.context['default_product_tmpl_id']
        records = super(type(self), self).create(vals_list)
        for record in records:
            record.x_check_duplicate_after_create()
            record._auto_assign_project_folder()
        return records

    def x_check_duplicate_after_create(self):
        try:
            domain = [
                ('x_document_type_id', '=', self.x_document_type_id.id),
                ('id', '!=', self.id),
            ]
            if self.x_project_id:
                domain.append(('x_project_id', '=', self.x_project_id.id))
            if self.x_task_id:
                domain.append(('x_task_id', '=', self.x_task_id.id))
            if self.x_product_tmpl_id:
                domain.append(('x_product_tmpl_id', '=', self.x_product_tmpl_id.id))
            duplicate_documents = self.search(domain)
            for duplicate in duplicate_documents:
                if self.x_attachment_ids and duplicate.x_attachment_ids:
                    self_attachment_ids = set(self.x_attachment_ids.ids)
                    dup_attachment_ids = set(duplicate.x_attachment_ids.ids)
                    if self_attachment_ids == dup_attachment_ids and self_attachment_ids:
                        # Optionally, add warning logic here
                        pass
        except Exception:
            pass

    def action_convert_x_attachments_to_documents(self):
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            _logger.info(f"[x_doc] Converting attachments for record {record.id} (project: {getattr(project, 'name', None)})")
            if not project:
                _logger.warning(f"[x_doc] No project for record {record.id}")
                continue
            # Ensure the project has a folder
            if not project.documents_folder_id:
                project._ensure_project_folder()
            if not project.documents_folder_id:
                _logger.warning(f"[x_doc] No project folder for record {record.id} after ensure.")
                continue
            _logger.info(f"[x_doc] Using folder: {getattr(project.documents_folder_id, 'name', None)} (ID: {getattr(project.documents_folder_id, 'id', None)})")
            for attachment in record.x_attachment_ids:
                _logger.info(f"[x_doc] Processing attachment {attachment.id} ({attachment.name}) for record {record.id}")
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                if not existing_doc:
                    doc = self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': project._name,
                        'res_id': project.id,
                        'type': 'binary',
                        'folder_id': project.documents_folder_id.id,
                    })
                    _logger.info(f"[x_doc] Created documents.document {doc.id} in folder {project.documents_folder_id.name}")
                else:
                    _logger.info(f"[x_doc] Attachment {attachment.id} already has documents.document {existing_doc.id}")

    # Add a button for user testing
    def button_convert_x_attachments(self):
        self.action_convert_x_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'x_Attachments converted to documents in project folder.',
                'type': 'success',
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._auto_convert_x_attachments()
        records._auto_assign_project_folder()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._auto_convert_x_attachments()
        # Check if attachments were added and copy them to project folder
        if 'x_attachment_ids' in vals:
            self._copy_attachments_to_project_folder()
        return res

    @api.onchange('x_project_id', 'x_task_id')
    def _onchange_project_auto_assign_folder(self):
        """Automatically assign project folder when project or task changes"""
        for record in self:
            if record.x_project_id or record.x_task_id:
                record._auto_assign_project_folder()

    def action_assign_project_folders(self):
        """Manual action to assign project folders to all documents"""
        self._auto_assign_project_folder()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Project folders assigned to {len(self)} document(s).',
                'type': 'success',
            }
        }

    def action_copy_attachments_to_project_folder(self):
        """Manual action to copy attachments to project folder"""
        self._copy_attachments_to_project_folder()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Attachments copied to project folder for {len(self)} document(s).',
                'type': 'success',
            }
        }

    def _auto_convert_x_attachments(self):
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            if not project:
                continue
            if not project.documents_folder_id:
                project._ensure_project_folder()
            for attachment in record.x_attachment_ids:
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                if not existing_doc:
                    self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': project._name,
                        'res_id': project.id,
                        'type': 'binary',
                        'folder_id': project.documents_folder_id.id,
                    })


class ProjectDeliverableDocument(models.Model):
    _name = 'project.deliverable.document'
    _inherits = {'documents.document': 'document_id'}
    _description = 'Deliverable Document for Project'

    document_id = fields.Many2one('documents.document', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', ondelete='cascade')
    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    deadline = fields.Date(string='Deadline')
    notes = fields.Text(string='Notes')
    name = fields.Char(related='document_id.name', string='Name', store=False, readonly=False)
    x_project_id = fields.Many2one('project.project', string='x_Project', ondelete='cascade')
    x_task_id = fields.Many2one('project.task', string='x_Task', ondelete='cascade')
    x_product_tmpl_id = fields.Many2one('product.template', string='x_Product Template', ondelete='cascade')
    x_document_type_id = fields.Many2one('project.document.type', string='x_Document Type')
    x_document_id = fields.Many2one('documents.document', string='x_Document')
    x_is_required = fields.Boolean(string='x_Required', default=False)
    x_expiry_date = fields.Date('x_Expiry Date')
    x_reminder_days = fields.Integer('x_Reminder Days', default=30)
    x_is_expired = fields.Boolean('x_Is Expired', default=False)
    x_is_verify = fields.Boolean('x_Is Verified', default=False)
    x_number = fields.Char(
        string="x_Number",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    x_issue_date = fields.Date(
        default=fields.Date.today,
        help="x_Date when the document was issued",
    )
    x_attachment_ids = fields.Many2many('ir.attachment', string='x_Attachments')
    x_expiration_reminder = fields.Boolean(default=False)
    x_expiration_reminder_sent = fields.Boolean(default=False)
    x_document_create_date = fields.Datetime(
        readonly=True,
        string="x_Document Create Date",
        default=fields.datetime.now(),
    )
    attachment_id = fields.Many2one('ir.attachment', related='document_id.attachment_id', string='Attachment', store=False, readonly=False) 
    project_folder_id = fields.Many2one(
        'documents.document', 
        string='Project Folder',
        domain="[('type', '=', 'folder')]",
        help="Folder in documents where this document will be stored"
    )
    
    def _auto_assign_project_folder(self):
        """Automatically assign project folder to the document"""
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            _logger.info(f"[AUTO_FOLDER] Record {record.id}: project={getattr(project, 'name', 'None')}, has_folder={bool(project and project.documents_folder_id)}, current_folder={getattr(record.project_folder_id, 'name', 'None')}")
            if project and project.documents_folder_id and not record.project_folder_id:
                record.project_folder_id = project.documents_folder_id.id
                _logger.info(f"[AUTO_FOLDER] ✅ Assigned folder '{project.documents_folder_id.name}' to record {record.id}")
            elif not project:
                _logger.warning(f"[AUTO_FOLDER] ⚠️ No project found for record {record.id}")
            elif not project.documents_folder_id:
                _logger.warning(f"[AUTO_FOLDER] ⚠️ Project '{project.name}' has no documents folder")
            elif record.project_folder_id:
                _logger.info(f"[AUTO_FOLDER] ℹ️ Record {record.id} already has folder '{record.project_folder_id.name}'")

    def _copy_attachments_to_project_folder(self):
        """Copy attachments to the project's documents folder"""
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            if not project or not project.documents_folder_id:
                _logger.warning(f"[COPY_ATTACHMENTS] ⚠️ No project or project folder found for record {record.id}")
                continue
            
            if not record.x_attachment_ids:
                _logger.info(f"[COPY_ATTACHMENTS] ℹ️ No attachments to copy for record {record.id}")
                continue
            
            _logger.info(f"[COPY_ATTACHMENTS] 📎 Copying {len(record.x_attachment_ids)} attachments to project folder '{project.documents_folder_id.name}'")
            
            for attachment in record.x_attachment_ids:
                try:
                    # Check if attachment is already in the project folder
                    existing_doc = self.env['documents.document'].search([
                        ('attachment_id', '=', attachment.id),
                        ('folder_id', '=', project.documents_folder_id.id)
                    ], limit=1)
                    
                    if existing_doc:
                        _logger.info(f"[COPY_ATTACHMENTS] ℹ️ Attachment '{attachment.name}' already exists in project folder")
                        continue
                    
                    # Create a new document in the project folder
                    new_doc = self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'folder_id': project.documents_folder_id.id,
                        'company_id': project.company_id.id,
                        'type': 'binary' if attachment.mimetype.startswith('image/') else 'url',
                    })
                    
                    _logger.info(f"[COPY_ATTACHMENTS] ✅ Successfully copied attachment '{attachment.name}' to project folder")
                    
                except Exception as e:
                    _logger.error(f"[COPY_ATTACHMENTS] ❌ Failed to copy attachment '{attachment.name}': {e}")

    @api.onchange('x_attachment_ids')
    def _onchange_attachments_copy_to_folder(self):
        """Trigger when attachments are added to copy them to project folder"""
        if self.x_attachment_ids:
            _logger.info(f"[ONCHANGE_ATTACHMENTS] 📎 Attachments changed for record {self.id}, will copy to project folder")
            # Note: onchange doesn't persist changes, so we'll handle this in write method
    
    # Computed field for dynamic name generation
    x_computed_name = fields.Char(
        string='x_Computed Name',
        compute='_compute_x_name',
        store=True,
        help='Dynamically generated name based on document type and template'
    )

    @api.depends('x_document_type_id', 'x_product_tmpl_id')
    def _compute_x_name(self):
        """Compute dynamic name based on document type and template ID"""
        for record in self:
            if record.x_document_type_id and record.x_product_tmpl_id:
                doc_type_name = record.x_document_type_id.name or ''
                template_name = record.x_product_tmpl_id.name or ''
                template_id = record.x_product_tmpl_id.id
                record.x_computed_name = f"{doc_type_name} - {template_name} (ID: {template_id})"
            elif record.x_document_type_id:
                record.x_computed_name = f"{record.x_document_type_id.name} - Document"
            else:
                record.x_computed_name = "Document"

    @api.depends('x_expiry_date')
    def x_compute_expired(self):
        try:
            today = fields.Date.today()
            for record in self:
                try:
                    if record.x_expiry_date:
                        is_expired = record.x_expiry_date < today
                        record.x_is_expired = is_expired
                    else:
                        record.x_is_expired = False
                except Exception:
                    record.x_is_expired = False
        except Exception:
            for record in self:
                record.x_is_expired = False

    def x_action_numbers(self):
        docs = self.env[self._name].sudo().search([])
        for doc in docs:
            doc.x_number = self.env['ir.sequence'].next_by_code(self._name) or _(u"New")

    @api.model_create_multi
    def x_create(self, vals_list):
        for vals in vals_list:
            if 'x_number' not in vals:
                vals['x_number'] = self.env['ir.sequence'].next_by_code(self._name) or _(u"New")
            # Set product_tmpl_id from context if available
            if 'product_tmpl_id' not in vals and self.env.context.get('default_product_tmpl_id'):
                vals['product_tmpl_id'] = self.env.context['default_product_tmpl_id']
            if 'x_product_tmpl_id' not in vals and self.env.context.get('default_product_tmpl_id'):
                vals['x_product_tmpl_id'] = self.env.context['default_product_tmpl_id']
        records = super(type(self), self).create(vals_list)
        for record in records:
            record.x_check_duplicate_after_create()
            record._auto_assign_project_folder()
        return records

    def x_check_duplicate_after_create(self):
        try:
            domain = [
                ('x_document_type_id', '=', self.x_document_type_id.id),
                ('id', '!=', self.id),
            ]
            if self.x_project_id:
                domain.append(('x_project_id', '=', self.x_project_id.id))
            if self.x_task_id:
                domain.append(('x_task_id', '=', self.x_task_id.id))
            if self.x_product_tmpl_id:
                domain.append(('x_product_tmpl_id', '=', self.x_product_tmpl_id.id))
            duplicate_documents = self.search(domain)
            for duplicate in duplicate_documents:
                if self.x_attachment_ids and duplicate.x_attachment_ids:
                    self_attachment_ids = set(self.x_attachment_ids.ids)
                    dup_attachment_ids = set(duplicate.x_attachment_ids.ids)
                    if self_attachment_ids == dup_attachment_ids and self_attachment_ids:
                        # Optionally, add warning logic here
                        pass
        except Exception:
            pass

    def action_convert_x_attachments_to_documents(self):
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            _logger.info(f"[x_doc] Converting attachments for record {record.id} (project: {getattr(project, 'name', None)})")
            if not project:
                _logger.warning(f"[x_doc] No project for record {record.id}")
                continue
            # Ensure the project has a folder
            if not project.documents_folder_id:
                project._ensure_project_folder()
            if not project.documents_folder_id:
                _logger.warning(f"[x_doc] No project folder for record {record.id} after ensure.")
                continue
            _logger.info(f"[x_doc] Using folder: {getattr(project.documents_folder_id, 'name', None)} (ID: {getattr(project.documents_folder_id, 'id', None)})")
            for attachment in record.x_attachment_ids:
                _logger.info(f"[x_doc] Processing attachment {attachment.id} ({attachment.name}) for record {record.id}")
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                if not existing_doc:
                    doc = self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': project._name,
                        'res_id': project.id,
                        'type': 'binary',
                        'folder_id': project.documents_folder_id.id,
                    })
                    _logger.info(f"[x_doc] Created documents.document {doc.id} in folder {project.documents_folder_id.name}")
                else:
                    _logger.info(f"[x_doc] Attachment {attachment.id} already has documents.document {existing_doc.id}")

    # Add a button for user testing
    def button_convert_x_attachments(self):
        self.action_convert_x_attachments_to_documents()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'x_Attachments converted to documents in project folder.',
                'type': 'success',
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._auto_convert_x_attachments()
        records._auto_assign_project_folder()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._auto_convert_x_attachments()
        # Check if attachments were added and copy them to project folder
        if 'x_attachment_ids' in vals:
            self._copy_attachments_to_project_folder()
        return res

    @api.onchange('x_project_id', 'x_task_id')
    def _onchange_project_auto_assign_folder(self):
        """Automatically assign project folder when project or task changes"""
        for record in self:
            if record.x_project_id or record.x_task_id:
                record._auto_assign_project_folder()

    def action_assign_project_folders(self):
        """Manual action to assign project folders to all documents"""
        self._auto_assign_project_folder()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Project folders assigned to {len(self)} document(s).',
                'type': 'success',
            }
        }

    def action_copy_attachments_to_project_folder(self):
        """Manual action to copy attachments to project folder"""
        self._copy_attachments_to_project_folder()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Attachments copied to project folder for {len(self)} document(s).',
                'type': 'success',
            }
        }

    def _auto_convert_x_attachments(self):
        for record in self:
            project = record.x_project_id or (record.x_task_id and record.x_task_id.project_id)
            if not project:
                continue
            if not project.documents_folder_id:
                project._ensure_project_folder()
            for attachment in record.x_attachment_ids:
                existing_doc = self.env['documents.document'].search([
                    ('attachment_id', '=', attachment.id)
                ], limit=1)
                if not existing_doc:
                    self.env['documents.document'].create({
                        'name': attachment.name,
                        'attachment_id': attachment.id,
                        'res_model': project._name,
                        'res_id': project.id,
                        'type': 'binary',
                        'folder_id': project.documents_folder_id.id,
                    })

# Inverse fields for project.project
class ProjectProject(models.Model):
    _inherit = 'project.project'
    x_required_document_ids = fields.One2many('project.required.document', 'x_project_id', string='x_Required Documents')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_project_id', string='x_Deliverable Documents')

    def _ensure_project_folder(self):
        """Ensure the project has a documents folder"""
        if not self.documents_folder_id:
            # Try to create a folder for the project
            try:
                # First, try to find the documents_project folder
                documents_project_folder = self.env.ref('documents_project.document_project_folder', raise_if_not_found=False)
                
                if documents_project_folder:
                    # Create a new folder for the project under the documents_project folder
                    folder = self.env['documents.document'].create({
                        'name': f'Project: {self.name}',
                        'type': 'folder',
                        'folder_id': documents_project_folder.id,
                        'company_id': self.company_id.id,
                    })
                else:
                    # Create a new folder for the project without parent
                    folder = self.env['documents.document'].create({
                        'name': f'Project: {self.name}',
                        'type': 'folder',
                        'company_id': self.company_id.id,
                    })
                
                self.documents_folder_id = folder.id
                _logger.info(f"[PROJECT_FOLDER] Created/assigned folder '{folder.name}' for project '{self.name}'")
                
            except Exception as e:
                _logger.error(f"[PROJECT_FOLDER] Failed to create folder for project '{self.name}': {e}")
                return False
        
        return True

    def action_assign_project_folders(self):
        """Assign project folders to all documents in this project"""
        # First, ensure the project has a documents folder
        if not self.documents_folder_id:
            _logger.info(f"[PROJECT_FOLDER] Project '{self.name}' has no documents folder, creating one...")
            if not self._ensure_project_folder():
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to create documents folder for project "{self.name}". Please check the logs for details.',
                        'type': 'danger',
                    }
                }
        
        if not self.documents_folder_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': f'Project "{self.name}" has no documents folder. Please set a documents folder for this project first.',
                    'type': 'warning',
                }
            }
        
        _logger.info(f"[PROJECT_FOLDER] Project '{self.name}' has documents folder: '{self.documents_folder_id.name}'")
        
        # Get all documents for this project
        required_docs = self.env['project.required.document'].search([('x_project_id', '=', self.id)])
        deliverable_docs = self.env['project.deliverable.document'].search([('x_project_id', '=', self.id)])
        
        _logger.info(f"[PROJECT_FOLDER] Found {len(required_docs)} required docs and {len(deliverable_docs)} deliverable docs")
        
        # Assign folders to required documents
        if required_docs:
            required_docs._auto_assign_project_folder()
        
        # Assign folders to deliverable documents
        if deliverable_docs:
            deliverable_docs._auto_assign_project_folder()
        
        total_docs = len(required_docs) + len(deliverable_docs)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Project folders assigned to {total_docs} document(s) in project "{self.name}". Please refresh the page to see the changes.',
                'type': 'success',
            }
        }

    def action_set_project_folder(self):
        """Manually set a documents folder for this project"""
        # Get all available folders
        folders = self.env['documents.document'].search([
            ('type', '=', 'folder')
        ])
        
        if not folders:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'No documents folders found. Please create a folder in Documents first.',
                    'type': 'warning',
                }
            }
        
        # Return action to open folder selection wizard
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Project Folder',
            'res_model': 'project.folder.selection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_project_id': self.id,
                'default_available_folders': [(6, 0, folders.ids)]
            }
        }

    def action_test_copy_attachments(self):
        """Test method to copy attachments from all documents in this project"""
        required_docs = self.env['project.required.document'].search([('x_project_id', '=', self.id)])
        deliverable_docs = self.env['project.deliverable.document'].search([('x_project_id', '=', self.id)])
        
        total_copied = 0
        
        # Copy attachments from required documents
        for doc in required_docs:
            doc._copy_attachments_to_project_folder()
            total_copied += len(doc.x_attachment_ids) if doc.x_attachment_ids else 0
        
        # Copy attachments from deliverable documents
        for doc in deliverable_docs:
            doc._copy_attachments_to_project_folder()
            total_copied += len(doc.x_attachment_ids) if doc.x_attachment_ids else 0
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Test completed: {total_copied} attachments processed from {len(required_docs) + len(deliverable_docs)} documents.',
                'type': 'success',
            }
        }

# Inverse fields for project.task
class ProjectTask(models.Model):
    _inherit = 'project.task'
    x_required_document_ids = fields.One2many('project.required.document', 'x_task_id', string='x_Required Documents')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_task_id', string='x_Deliverable Documents')

# Inverse fields for documents.document
class DocumentsDocument(models.Model):
    _inherit = 'documents.document'
    x_required_document_ids = fields.One2many('project.required.document', 'x_document_id', string='x_Required Document Lines')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_document_id', string='x_Deliverable Document Lines')
    project_folder_id = fields.Many2one(
        'documents.document', 
        string='Project Folder',
        domain="[('type', '=', 'folder')]",
        help="Folder in documents where this document will be stored"
    )

# Inverse fields for project.document.type
class ProjectDocumentType(models.Model):
    _inherit = 'project.document.type'
    x_required_document_ids = fields.One2many('project.required.document', 'x_document_type_id', string='x_Required Document Lines')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_document_type_id', string='x_Deliverable Document Lines') 