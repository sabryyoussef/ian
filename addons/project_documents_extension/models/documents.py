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
                        'type': 'file',
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
        return records

    def write(self, vals):
        res = super().write(vals)
        self._auto_convert_x_attachments()
        return res

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
                        'type': 'file',
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
                        'type': 'file',
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
        return records

    def write(self, vals):
        res = super().write(vals)
        self._auto_convert_x_attachments()
        return res

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
                        'type': 'file',
                        'folder_id': project.documents_folder_id.id,
                    })

# Inverse fields for project.project
class ProjectProject(models.Model):
    _inherit = 'project.project'
    x_required_document_ids = fields.One2many('project.required.document', 'x_project_id', string='x_Required Documents')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_project_id', string='x_Deliverable Documents')

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

# Inverse fields for project.document.type
class ProjectDocumentType(models.Model):
    _inherit = 'project.document.type'
    x_required_document_ids = fields.One2many('project.required.document', 'x_document_type_id', string='x_Required Document Lines')
    x_deliverable_document_ids = fields.One2many('project.deliverable.document', 'x_document_type_id', string='x_Deliverable Document Lines') 